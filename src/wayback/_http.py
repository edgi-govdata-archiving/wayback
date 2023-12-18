"""
HTTP tooling used by Wayback when making requests and handling responses.
"""

import logging
import re
import time
from typing import Generator, Optional
from urllib.parse import urlencode, urljoin, urlparse
from urllib3 import HTTPResponse, PoolManager, Timeout as Urllib3Timeout
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import (ConnectTimeoutError,
                                DecodeError,
                                MaxRetryError,
                                ProtocolError,
                                ReadTimeoutError,
                                ProxyError,
                                TimeoutError)
# The Header dict lives in a different place for urllib3 v2:
try:
    from urllib3 import HTTPHeaderDict as Urllib3HTTPHeaderDict
# vs. urllib3 v1:
except ImportError:
    from urllib3.response import HTTPHeaderDict as Urllib3HTTPHeaderDict

from . import _utils, __version__
from .exceptions import (WaybackRetryError,
                         RateLimitError,
                         SessionClosedError)


logger = logging.getLogger(__name__)

# Global default rate limits for various endpoints. Internet Archive folks have
# asked us to set the defaults at 80% of the hard limits.
DEFAULT_CDX_RATE_LIMIT = _utils.RateLimit(0.8 * 60 / 60)
DEFAULT_TIMEMAP_RATE_LIMIT = _utils.RateLimit(0.8 * 100 / 60)
DEFAULT_MEMENTO_RATE_LIMIT = _utils.RateLimit(0.8 * 600 / 60)

# If a rate limit response (i.e. a response with status == 429) does not
# include a `Retry-After` header, recommend pausing for this long.
DEFAULT_RATE_LIMIT_DELAY = 60


#####################################################################
# HACK: handle malformed Content-Encoding headers from Wayback.
# When you send `Accept-Encoding: gzip` on a request for a memento, Wayback
# will faithfully gzip the response body. However, if the original response
# from the web server that was snapshotted was gzipped, Wayback screws up the
# `Content-Encoding` header on the memento response, leading any HTTP client to
# *not* decompress the gzipped body. Wayback folks have no clear timeline for
# a fix, hence the workaround here.
#
# More info in this issue:
# https://github.com/edgi-govdata-archiving/web-monitoring-processing/issues/309
#
# Example broken Wayback URL:
# http://web.archive.org/web/20181023233237id_/http://cwcgom.aoml.noaa.gov/erddap/griddap/miamiacidification.graph
#
if hasattr(HTTPConnectionPool, 'ResponseCls'):
    # urllib3 v1.x:
    #
    # This subclass of urllib3's response class identifies the malformed headers
    # and repairs them before instantiating the actual response object, so when
    # it reads the body, it knows to decode it correctly.
    #
    # See what we're overriding from urllib3:
    # https://github.com/urllib3/urllib3/blob/a6ec68a5c5c5743c59fe5c62c635c929586c429b/src/urllib3/response.py#L499-L526
    class WaybackUrllibResponse(HTTPConnectionPool.ResponseCls):
        @classmethod
        def from_httplib(cls, httplib_response, **response_kwargs):
            headers = httplib_response.msg
            pairs = headers.items()
            if ('content-encoding', '') in pairs and ('Content-Encoding', 'gzip') in pairs:
                del headers['content-encoding']
                headers['Content-Encoding'] = 'gzip'
            return super().from_httplib(httplib_response, **response_kwargs)

    HTTPConnectionPool.ResponseCls = WaybackUrllibResponse
else:
    # urllib3 v2.x:
    #
    # Unfortunately, we can't wrap the `HTTPConnection.getresponse` method in
    # urllib3 v2, since it may have read the response body before returning. So
    # we patch the HTTPHeaderDict class instead.
    _urllib3_header_init = Urllib3HTTPHeaderDict.__init__

    def _new_header_init(self, headers=None, **kwargs):
        if headers:
            if isinstance(headers, (Urllib3HTTPHeaderDict, dict)):
                pairs = list(headers.items())
            else:
                pairs = list(headers)
            if (
                ('content-encoding', '') in pairs and
                ('Content-Encoding', 'gzip') in pairs
            ):
                headers = [pair for pair in pairs
                           if pair[0].lower() != 'content-encoding']
                headers.append(('Content-Encoding', 'gzip'))

        return _urllib3_header_init(self, headers, **kwargs)

    Urllib3HTTPHeaderDict.__init__ = _new_header_init
# END HACK
#####################################################################


def is_memento_response(response: 'InternalHttpResponse'):
    return 'Memento-Datetime' in response.headers


def iter_byte_slices(data: bytes, size: int) -> Generator[bytes, None, None]:
    """
    Iterate over groups of N bytes from some original bytes. In Python 3.12+,
    this can be done with ``itertools.batched()``.
    """
    index = 0
    if size <= 0:
        size = len(data)
    while index < len(data):
        yield data[index:index + size]
        index += size


# XXX: pretty much wholesale taken from requests. May need adjustment.
def parse_header_links(value):
    """Return a list of parsed link headers proxies.

    i.e. Link: <http:/.../front.jpeg>; rel=front; type="image/jpeg",
               <http://.../back.jpeg>; rel=back;type="image/jpeg"

    :rtype: list
    """

    links = []

    replace_chars = " '\""

    value = value.strip(replace_chars)
    if not value:
        return links

    for val in re.split(", *<", value):
        try:
            url, params = val.split(";", 1)
        except ValueError:
            url, params = val, ""

        link = {"url": url.strip("<> '\"")}

        for param in params.split(";"):
            try:
                key, value = param.split("=")
            except ValueError:
                break

            link[key.strip(replace_chars)] = value.strip(replace_chars)

        links.append(link)

    return links


# XXX: pretty much wholesale taken from requests. May need adjustment.
# https://github.com/psf/requests/blob/147c8511ddbfa5e8f71bbf5c18ede0c4ceb3bba4/requests/models.py#L107-L134
def serialize_querystring(data):
    """Encode parameters in a piece of data.

    Will successfully encode parameters when passed as a dict or a list of
    2-tuples. Order is retained if data is a list of 2-tuples but arbitrary
    if parameters are supplied as a dict.
    """
    if data is None:
        return None
    if isinstance(data, (str, bytes)):
        return data
    elif hasattr(data, "read"):
        return data
    elif hasattr(data, "__iter__"):
        result = []
        for k, vs in list(data.items()):
            if isinstance(vs, str) or not hasattr(vs, "__iter__"):
                vs = [vs]
            for v in vs:
                if v is not None:
                    result.append(
                        (
                            k.encode("utf-8") if isinstance(k, str) else k,
                            v.encode("utf-8") if isinstance(v, str) else v,
                        )
                    )
        return urlencode(result, doseq=True)
    else:
        return data


# XXX: pretty much wholesale taken from requests. May need adjustment.
# We have some similar code in `test/support.py`, and we should probably figure
# out how to merge these.
def _parse_content_type_header(header):
    """Returns content type and parameters from given header

    :param header: string
    :return: tuple containing content type and dictionary of
         parameters
    """

    tokens = header.split(";")
    content_type, params = tokens[0].strip(), tokens[1:]
    params_dict = {}
    items_to_strip = "\"' "

    for param in params:
        param = param.strip()
        if param:
            key, value = param, True
            index_of_equals = param.find("=")
            if index_of_equals != -1:
                key = param[:index_of_equals].strip(items_to_strip)
                value = param[index_of_equals + 1:].strip(items_to_strip)
            params_dict[key.lower()] = value
    return content_type, params_dict


# XXX: pretty much wholesale taken from requests. May need adjustment.
def get_encoding_from_headers(headers):
    """Returns encodings from given HTTP Header Dict.

    :param headers: dictionary to extract encoding from.
    :rtype: str
    """

    content_type = headers.get("content-type")

    if not content_type:
        return None

    content_type, params = _parse_content_type_header(content_type)

    if "charset" in params:
        return params["charset"].strip("'\"")

    # XXX: Browsers today actually use Windows-1252 as the standard default
    # (some TLDs have a different default), per WHATWG.
    # ISO-8859-1 comes from requests, maybe we should change it? It makes sense
    # for us to generally act more like a browser than a generic HTTP tool, but
    # also probably not a big deal.
    if "text" in content_type:
        return "ISO-8859-1"

    if "application/json" in content_type:
        # Assume UTF-8 based on RFC 4627: https://www.ietf.org/rfc/rfc4627.txt since the charset was unset
        return "utf-8"


# XXX: Everything that lazily calculates an underscore-prefixed property here
# needs an Lock, or needs to precalculate its value in the constructor or some
# sort of builder function.
class InternalHttpResponse:
    """
    Internal wrapper class for HTTP responses. THIS SHOULD NEVER BE EXPOSED TO
    USER CODE. This makes some things from urllib3 a little easier to deal with,
    like parsing special headers, caching body content, etc.

    This is *similar* to response objects from httpx and requests, although it
    lacks facilities from those libraries that we don't need or use, and takes
    shortcuts that are specific to our use cases.
    """
    raw: HTTPResponse
    status_code: int
    headers: Urllib3HTTPHeaderDict
    encoding: Optional[str] = None
    url: str
    _content: Optional[bytes] = None
    _text: Optional[str] = None
    _redirect_url: Optional[str] = None

    def __init__(self, raw: HTTPResponse, request_url: str) -> None:
        self.raw = raw
        self.status_code = raw.status
        self.headers = raw.headers
        self.url = urljoin(request_url, getattr(raw, 'url', ''))
        self.encoding = get_encoding_from_headers(self.headers)

    # XXX: shortcut to essentially what requests does in `iter_content()`.
    # Requests has a weird thing where it uses `raw.stream()` if present, but
    # always passes `decode_content=True` to it when it does the opposite for
    # `raw.read()` (when `stream()` is not present). This is confusing!
    #   https://github.com/psf/requests/blob/147c8511ddbfa5e8f71bbf5c18ede0c4ceb3bba4/requests/models.py#L812-L833
    #
    # - `stream()` has been around since urllib3 v1.10.3 (released 2015-04-21).
    #   Seems like you could just depend on it being there. Two theories:
    #   A) requests just has a lot of old code hanging around, or
    #   B) VCR or some mocking libraries don't implement `stream`, and just give
    #      requests a file-like.
    #   If (B), we ought to see problems in tests.
    #
    # - Looking at urllib3, `stream()` should just call `read()`, so I wouldn't
    #   think you'd want to pass a different value for `decode_content`!
    #     https://github.com/urllib3/urllib3/blob/90c30f5fdca56a54248614dc86570bf2692a4caa/src/urllib3/response.py#L1001-L1026
    #   Theory: this is actual about compression (via the content-encoding
    #   header), not text encoding. The differing values still seems like a bug,
    #   but assuming we always wind up using `stream()`, then it makes sense
    #   to always set this to `True` (always decompress).
    def stream(self, chunk_size: int = 10 * 1024) -> Generator[bytes, None, None]:
        # If content was preloaded, it'll be in `._body`, but some mocking
        # tools are missing the attribute altogether.
        body = getattr(self.raw, '_body', None)
        if body:
            yield from iter_byte_slices(body, chunk_size)
        else:
            yield from self.raw.stream(chunk_size, decode_content=True)
        self._release_conn()

    @property
    def content(self) -> bytes:
        if self._content is None:
            self._content = b"".join(self.stream()) or b""

        return self._content

    @property
    def text(self) -> str:
        if self._text is None:
            encoding = self.encoding or self.sniff_encoding() or 'utf-8'
            try:
                self._text = str(self.content, encoding, errors="replace")
            except (LookupError, TypeError):
                self._text = str(self.content, errors="replace")

        return self._text

    def sniff_encoding(self) -> None:
        # XXX: requests uses chardet here. Consider what we want to use.
        ...

    @property
    def links(self) -> dict:
        """Returns the parsed header links of the response, if any."""

        header = self.headers.get("link")

        resolved_links = {}

        if header:
            links = parse_header_links(header)

            for link in links:
                key = link.get("rel") or link.get("url")
                resolved_links[key] = link

        return resolved_links

    @property
    def redirect_url(self) -> str:
        """
        The URL this response redirects to. If the response is not a redirect,
        this returns an empty string.
        """
        if self._redirect_url is None:
            url = ''
            if self.status_code >= 300 and self.status_code < 400:
                location = self.headers.get('location')
                if location:
                    url = urljoin(self.url, location)
            self._redirect_url = url
        return self._redirect_url

    @property
    def is_success(self) -> bool:
        return self.status_code >= 200 and self.status_code < 300

    # XXX: This and _release_conn probably need wrapping with RLock!
    def close(self, cache: bool = True) -> None:
        """
        Read the rest of the response off the wire and release the connection.
        If the full response is not read, the connection can hang your program
        will leak memory (and cause a bad time for the server as well).

        Parameters
        ----------
        cache : bool, default: True
            Whether to cache the response body so it can still be used via the
            ``content`` and ``text`` properties.
        """
        if self.raw:
            try:
                if cache:
                    # Inspired by requests: https://github.com/psf/requests/blob/eedd67462819f8dbf8c1c32e77f9070606605231/requests/sessions.py#L160-L163  # noqa
                    try:
                        self.content
                    except (DecodeError, ProtocolError, RuntimeError):
                        self.raw.drain_conn()
                else:
                    self.raw.drain_conn()
            finally:
                self._release_conn()

    def _release_conn(self) -> None:
        "Release the connection. Make sure to drain it first!"
        if self.raw:
            # Some mocks (e.g. VCR) are missing `.release_conn`
            release_conn = getattr(self.raw, 'release_conn', None)
            if release_conn is None:
                # self.raw.close()
                ...
            else:
                release_conn()
            # Let go of the raw urllib3 response so we can't accidentally read
            # it later when its connection might be re-used.
            self.raw = None


class WaybackSession:
    """
    Manages HTTP requests to Wayback Machine servers, handling things like
    retries, rate limiting, connection pooling, timeouts, etc.

    Parameters
    ----------
    retries : int, default: 6
        The maximum number of retries for requests.
    backoff : int or float, default: 2
        Number of seconds from which to calculate how long to back off and wait
        when retrying requests. The first retry is always immediate, but
        subsequent retries increase by powers of 2:

            seconds = backoff * 2 ^ (retry number - 1)

        So if this was `4`, retries would happen after the following delays:
        0 seconds, 4 seconds, 8 seconds, 16 seconds, ...
    timeout : int or float or tuple of (int or float, int or float), default: 60
        A timeout to use for all requests.
        See the Requests docs for more:
        https://docs.python-requests.org/en/master/user/advanced/#timeouts
    user_agent : str, optional
        A custom user-agent string to use in all requests. Defaults to:
        `wayback/{version} (+https://github.com/edgi-govdata-archiving/wayback)`
    search_calls_per_second : wayback.RateLimit or int or float, default: 0.8
        The maximum number of calls per second made to the CDX search API.
        To disable the rate limit, set this to 0.

        To have multiple sessions share a rate limit (so requests made by one
        session count towards the limit of the other session), use a
        single :class:`wayback.RateLimit` instance and pass it to each
        ``WaybackSession`` instance. If you do not set a limit, the default
        limit is shared globally across all sessions.
    memento_calls_per_second : wayback.RateLimit or int or float, default: 8
        The maximum number of calls per second made to the memento API.
        To disable the rate limit, set this to 0.

        To have multiple sessions share a rate limit (so requests made by one
        session count towards the limit of the other session), use a
        single :class:`wayback.RateLimit` instance and pass it to each
        ``WaybackSession`` instance. If you do not set a limit, the default
        limit is shared globally across all sessions.
    timemap_calls_per_second : wayback.RateLimit or int or float, default: 1.33
        The maximum number of calls per second made to the timemap API (the
        Wayback Machine's new, beta CDX search is part of the timemap API).
        To disable the rate limit, set this to 0.

        To have multiple sessions share a rate limit (so requests made by one
        session count towards the limit of the other session), use a
        single :class:`wayback.RateLimit` instance and pass it to each
        ``WaybackSession`` instance. If you do not set a limit, the default
        limit is shared globally across all sessions.
    """

    # It seems Wayback sometimes produces 500 errors for transient issues, so
    # they make sense to retry here. Usually not in other contexts, though.
    retryable_statuses = frozenset((413, 421, 500, 502, 503, 504, 599))

    # XXX: TimeoutError should be a base class for both ConnectTimeoutError
    # and ReadTimeoutError, so we don't need them here...?
    retryable_errors = (ConnectTimeoutError, MaxRetryError, ReadTimeoutError,
                        ProxyError, TimeoutError,
                        # XXX: These used to be wrapped with
                        # requests.ConnectionError, which we would then have to
                        # inspect to see if it needed retrying. Need to make
                        # sure/think through whether these should be retried.
                        ProtocolError, OSError)
    # Handleable errors *may* be retryable, but need additional logic beyond
    # just the error type. See `should_retry_error()`.
    #
    # XXX: see notes above about what should get retried; which things need to
    # be caught but then more deeply inspected, blah blah blah:
    # handleable_errors = (ConnectionError,) + retryable_errors
    handleable_errors = () + retryable_errors

    def __init__(self, retries=6, backoff=2, timeout=60, user_agent=None,
                 search_calls_per_second=DEFAULT_CDX_RATE_LIMIT,
                 memento_calls_per_second=DEFAULT_MEMENTO_RATE_LIMIT,
                 timemap_calls_per_second=DEFAULT_TIMEMAP_RATE_LIMIT):
        super().__init__()
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.headers = {
            'User-Agent': (user_agent or
                           f'wayback/{__version__} (+https://github.com/edgi-govdata-archiving/wayback)'),
            'Accept-Encoding': 'gzip, deflate'
        }
        self.rate_limts = {
            '/web/timemap': _utils.RateLimit.make_limit(timemap_calls_per_second),
            '/cdx': _utils.RateLimit.make_limit(search_calls_per_second),
            # The memento limit is actually a generic Wayback limit.
            '/': _utils.RateLimit.make_limit(memento_calls_per_second),
        }
        # XXX: These parameters are the same as requests, but we have had at
        # least one user reach in and change the adapters we used with requests
        # to modify these. We should consider whether different values are
        # appropriate (e.g. block=True) or if these need to be exposed somehow.
        #
        # XXX: Consider using a HTTPSConnectionPool instead of a PoolManager.
        # We can make some code simpler if we are always assuming the same host.
        # (At current, we only use one host, so this is feasible.)
        #
        # XXX: Do we need a cookie jar? urllib3 doesn't do any cookie management
        # for us, and the Wayback Machine may set some cookies we should retain
        # in subsequent requests. (In practice, it doesn't appear the CDX,
        # Memento, or Timemap APIs do by default, but not sure what happens if
        # you send S3-style credentials or use other endpoints.)
        self._pool_manager = PoolManager(
            num_pools=10,
            maxsize=10,
            block=False,
        )
        # NOTE: the nice way to accomplish retry/backoff is with a urllib3:
        #     adapter = requests.adapters.HTTPAdapter(
        #         max_retries=Retry(total=5, backoff_factor=2,
        #                           status_forcelist=(503, 504)))
        #     self.mount('http://', adapter)
        # But Wayback mementos can have errors, which complicates things. See:
        # https://github.com/urllib3/urllib3/issues/1445#issuecomment-422950868
        #
        # Also note that, if we are ever able to switch to that, we may need to
        # get more fancy with log filtering, since we *expect* lots of retries
        # with Wayback's APIs, but urllib3 logs a warning on every retry:
        # https://github.com/urllib3/urllib3/blob/5b047b645f5f93900d5e2fc31230848c25eb1f5f/src/urllib3/connectionpool.py#L730-L737

    def request(self, method, url, *, params=None, allow_redirects=True, timeout=-1) -> InternalHttpResponse:
        if not self._pool_manager:
            raise SessionClosedError('This session has already been closed '
                                     'and cannot send new HTTP requests.')

        start_time = time.time()
        maximum = self.retries
        retries = 0

        timeout = self.timeout if timeout is -1 else timeout
        # XXX: grabbed from requests. Clean up for our use case.
        if isinstance(timeout, tuple):
            try:
                connect, read = timeout
                timeout = Urllib3Timeout(connect=connect, read=read)
            except ValueError:
                raise ValueError(
                    f"Invalid timeout {timeout}. Pass a (connect, read) timeout tuple, "
                    f"or a single float to set both timeouts to the same value."
                )
        elif isinstance(timeout, Urllib3Timeout):
            pass
        else:
            timeout = Urllib3Timeout(connect=timeout, read=timeout)

        parsed = urlparse(url)
        for path, limit in self.rate_limts.items():
            if parsed.path.startswith(path):
                rate_limit = limit
                break
        else:
            rate_limit = DEFAULT_MEMENTO_RATE_LIMIT

        # Do our own querystring work since urllib3 serializes lists poorly.
        if params:
            serialized = serialize_querystring(params)
            if parsed.query:
                url += f'&{serialized}'
            else:
                url += f'?{serialized}'

        while True:
            retry_delay = 0
            try:
                # XXX: should be `debug()`. Set to warning to testing.
                logger.warning('sending HTTP request %s "%s", %s', method, url, params)
                rate_limit.wait()
                response = InternalHttpResponse(self._pool_manager.request(
                    method=method,
                    url=url,
                    # fields=serialize_querystring(params),
                    headers=self.headers,
                    # XXX: is allow_redirects safe for preload_content == False?
                    # XXX: it is, BUT THAT SKIPS OUR RATE LIMITING, which also
                    # is obviously already a problem today, but we ought to get
                    # it fixed now. Leaving this on for the moment, but it
                    # must be addressed before merging.
                    redirect=allow_redirects,
                    preload_content=False,
                    timeout=timeout
                ), url)

                retry_delay = self.get_retry_delay(retries, response)

                if retries >= maximum or not self.should_retry(response):
                    if response.status_code == 429:
                        response.close()
                        raise RateLimitError(response, retry_delay)
                    return response
                else:
                    logger.debug('Received error response (status: %s), will retry', response.status_code)
                    response.close(cache=False)
            # XXX: urllib3's MaxRetryError can wrap all the other errors, so
            # we should probably be checking `error.reason` on it. See how
            # requests handles this:
            #   https://github.com/psf/requests/blob/a25fde6989f8df5c3d823bc9f2e2fc24aa71f375/src/requests/adapters.py#L502-L537
            #
            # XXX: requests.RetryError used to be in our list of handleable
            # errors; it gets raised when urllib3 raises a MaxRetryError with a
            # ResponseError for its `reason` attribute. Need to test the
            # situation here...
            #
            # XXX: Consider how read-related exceptions need to be handled (or
            # not). In requests:
            #   https://github.com/psf/requests/blob/a25fde6989f8df5c3d823bc9f2e2fc24aa71f375/src/requests/models.py#L794-L839
            except WaybackSession.handleable_errors as error:
                response = getattr(error, 'response', None)
                if response is not None:
                    response.close()

                if retries >= maximum:
                    raise WaybackRetryError(retries, time.time() - start_time, error) from error
                elif self.should_retry_error(error):
                    retry_delay = self.get_retry_delay(retries, response)
                    logger.info('Caught exception during request, will retry: %s', error)
                else:
                    raise

            logger.debug('Will retry after sleeping for %s seconds...', retry_delay)
            time.sleep(retry_delay)
            retries += 1

    def should_retry(self, response: InternalHttpResponse):
        # A memento may actually be a capture of an error, so don't retry it :P
        if is_memento_response(response):
            return False

        return response.status_code in self.retryable_statuses

    def should_retry_error(self, error):
        if isinstance(error, WaybackSession.retryable_errors):
            return True
        # XXX: ConnectionError was a broad wrapper from requests; there are more
        # narrow errors in urllib3 we can catch, so this is probably (???) no
        # longer relevant. But urllib3 has some other wrapper exceptions that we
        # might need to dig into more, see:
        # https://github.com/psf/requests/blob/a25fde6989f8df5c3d823bc9f2e2fc24aa71f375/src/requests/adapters.py#L502-L537
        #
        # elif isinstance(error, ConnectionError):
        #     # ConnectionErrors from requests actually wrap a whole family of
        #     # more detailed errors from urllib3, so we need to do some string
        #     # checking to determine whether the error is retryable.
        #     text = str(error)
        #     # NOTE: we have also seen this, which may warrant retrying:
        #     # `requests.exceptions.ConnectionError: ('Connection aborted.',
        #     # RemoteDisconnected('Remote end closed connection without
        #     # response'))`
        #     if 'NewConnectionError' in text or 'Max retries' in text:
        #         return True

        return False

    def get_retry_delay(self, retries, response: InternalHttpResponse = None):
        delay = 0

        # As of 2023-11-27, the Wayback Machine does not set a `Retry-After`
        # header, so this parsing is just future-proofing.
        if response is not None:
            delay = _utils.parse_retry_after(response.headers.get('Retry-After')) or delay
            if response.status_code == 429 and delay == 0:
                delay = DEFAULT_RATE_LIMIT_DELAY

        # No default backoff on the first retry.
        if retries > 0:
            delay = max(self.backoff * 2 ** (retries - 1), delay)

        return delay

    # XXX: Needs to do the right thing. Requests sessions closed all their
    # adapters, which does:
    #     self.poolmanager.clear()
    #     for proxy in self.proxy_manager.values():
    #         proxy.clear()
    def reset(self):
        "Reset any network connections the session is using."
        self._pool_manager.clear()

    def close(self) -> None:
        if self._pool_manager:
            self._pool_manager.clear()
            self._pool_manager = None
