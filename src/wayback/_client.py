"""
This module provides a Python API for accessing versions (timestamped captures)
of a URL. There are existing open-source Python packages for the Internet
Archive API (the best-established one seems to be
https://internetarchive.readthedocs.io/en/latest/) but none that expose the
list of versions of a URL.

References used in writing this module:
* https://ws-dl.blogspot.fr/2013/07/2013-07-15-wayback-machine-upgrades.html

Other potentially useful links:
* https://blog.archive.org/developers/
* https://archive.readme.io/docs/memento
"""

from base64 import b32encode
from datetime import date
from enum import Enum
import hashlib
import logging
import re
# import requests
# from requests.exceptions import (ChunkedEncodingError,
#                                  ConnectionError,
#                                  ContentDecodingError,
#                                  ProxyError,
#                                  RetryError,
#                                  Timeout)
import time
from typing import Generator, Optional
from urllib.parse import urlencode, urljoin, urlparse
from urllib3 import PoolManager, HTTPResponse, Timeout as Urllib3Timeout
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

from warnings import warn
from . import _utils, __version__
from ._http import FIXME  # noqa
from ._models import CdxRecord, Memento
from .exceptions import (WaybackException,
                         UnexpectedResponseFormat,
                         BlockedByRobotsError,
                         BlockedSiteError,
                         MementoPlaybackError,
                         NoMementoError,
                         WaybackRetryError,
                         RateLimitError,
                         SessionClosedError)


logger = logging.getLogger(__name__)

CDX_SEARCH_URL = 'https://web.archive.org/cdx/search/cdx'
# This /web/timemap URL has newer features, but has other bugs and doesn't
# support some features, like resume keys (for paging). It ignores robots.txt,
# while /cdx/search obeys robots.txt (for now). It also has different/extra
# columns. See
# https://github.com/internetarchive/wayback/blob/bd205b9b26664a6e2ea3c0c2a8948f0dc6ff4519/wayback-cdx-server/src/main/java/org/archive/cdxserver/format/CDX11Format.java#L13-L17  # noqa
# NOTE: the `length` and `robotflags` fields appear to always be empty
# TODO: support new/upcoming CDX API
# CDX_SEARCH_URL = 'https://web.archive.org/web/timemap/cdx'

REDUNDANT_HTTP_PORT = re.compile(r'^(http://[^:/]+):80(.*)$')
REDUNDANT_HTTPS_PORT = re.compile(r'^(https://[^:/]+):443(.*)$')
DATA_URL_START = re.compile(r'data:[\w]+/[\w]+;base64')
# Matches URLs w/ users w/no pass, e-mail addresses, and mailto: URLs. These
# basically look like an e-mail or mailto: got `http://` pasted in front, e.g:
#   http://b***z@pnnl.gov/
#   http://@pnnl.gov/
#   http://mailto:first.last@pnnl.gov/
#   http://<<mailto:first.last@pnnl.gov>>/
EMAILISH_URL = re.compile(r'^https?://(<*)((mailto:)|([^/@:]*@))')
# Make sure it roughly starts with a valid protocol + domain + port?
URL_ISH = re.compile(r'^[\w+\-]+://[^/?=&]+\.\w\w+(:\d+)?(/|$)')

# Global default rate limits for various endpoints. Internet Archive folks have
# asked us to set the defaults at 80% of the hard limits.
DEFAULT_CDX_RATE_LIMIT = _utils.RateLimit(0.8 * 60 / 60)
DEFAULT_TIMEMAP_RATE_LIMIT = _utils.RateLimit(0.8 * 100 / 60)
DEFAULT_MEMENTO_RATE_LIMIT = _utils.RateLimit(0.8 * 600 / 60)

# If a rate limit response (i.e. a response with status == 429) does not
# include a `Retry-After` header, recommend pausing for this long.
DEFAULT_RATE_LIMIT_DELAY = 60


class Mode(Enum):
    """
    An enum describing the playback mode of a memento. When requesting a
    memento (e.g. with :meth:`wayback.WaybackClient.get_memento`), you can use
    these values to determine how the response body should be formatted.

    For more details, see:
    https://archive-access.sourceforge.net/projects/wayback/administrator_manual.html#Archival_URL_Replay_Mode

    Examples
    --------
    >>> waybackClient.get_memento('https://noaa.gov/',
    >>>                           timestamp=datetime.datetime(2018, 1, 2),
    >>>                           mode=wayback.Mode.view)

    **Values**

    .. py:attribute:: original

        Returns the HTTP response body as originally captured.

    .. py:attribute:: view

        Formats the response body so it can be viewed with a web
        browser. URLs for links and subresources like scripts, stylesheets,
        images, etc. will be modified to point to the equivalent memento in the
        Wayback Machine so that the resulting page looks as similar as possible
        to how it would have appeared when originally captured. It's mainly meant
        for use with HTML pages. This is the playback mode you typically use when
        browsing the Wayback Machine with a web browser.

    .. py:attribute:: javascript

        Formats the response body by updating URLs, similar
        to ``Mode.view``, but designed for JavaScript instead of HTML.

    .. py:attribute:: css

        Formats the response body by updating URLs, similar to
        ``Mode.view``, but designed for CSS instead of HTML.

    .. py:attribute:: image

        formats the response body similar to ``Mode.view``, but
        designed for image files instead of HTML.
    """
    original = 'id_'
    view = ''
    javascript = 'js_'
    css = 'cs_'
    image = 'im_'


def is_malformed_url(url):
    if DATA_URL_START.search(url):
        return True

    # TODO: restrict to particular protocols?
    if url.startswith('mailto:') or EMAILISH_URL.match(url):
        return True

    if URL_ISH.match(url) is None:
        return True

    return False


def is_memento_response(response):
    return 'Memento-Datetime' in response.headers


def cdx_hash(content):
    if isinstance(content, str):
        content = content.encode()
    return b32encode(hashlib.sha1(content).digest()).decode()


REDIRECT_PAGE_PATTERN = re.compile(r'Got an? HTTP 3\d\d response at crawl time', re.IGNORECASE)


def detect_view_mode_redirect(response, current_date):
    """
    Given a response for a page in view mode, detect whether it represents
    a historical redirect and return the target URL or ``None``.

    In view mode, historical redirects aren't served as actual 3xx
    responses. Instead, they are a normal web page that displays information
    about the redirect. After a short delay, JavaScript on the page
    redirects the browser. That obviously doesn't work great for us! The
    goal here is to detect that we got one of those pages and extract the
    URL that was redirected to.

    If the page looks like a redirect but we can't find the target URL,
    this raises an exception.
    """
    if (
        response.status_code == 200
        and 'x-archive-src' in response.headers
        and REDIRECT_PAGE_PATTERN.search(response.text)
    ):
        # The page should have a link to the redirect target. Only look for URLs
        # using the same timestamp to reduce the chance of picking up some other
        # link that isn't about the redirect.
        current_timestamp = _utils.format_timestamp(current_date)
        redirect_match = re.search(fr'''
            <a\s                              # <a> element
            (?:[^>\s]+\s)*                    # Possible other attributes
            href=(["\'])                      # href attribute and quote
            (                                 # URL of another archived page with the same timestamp
                (?:(?:https?:)//[^/]+)?       # Optional schema and host
                /web/{current_timestamp}/.*?
            )
            \1                                # End quote
            [\s|>]                            # Space before another attribute or end of element
        ''', response.text, re.VERBOSE | re.IGNORECASE)

        if redirect_match:
            redirect_url = redirect_match.group(2)
            if redirect_url.startswith('/'):
                redirect_url = urljoin(response.url, redirect_url)

            return redirect_url
        else:
            raise WaybackException(
                'The server sent a response in `view` mode that looks like a redirect, '
                'but the URL to redirect to could not be found on the page. Please file '
                'an issue at  https://github.com/edgi-govdata-archiving/wayback/issues/ '
                'with details about what happened.'
            )

    return None


def clean_memento_links(links, mode):
    """
    Clean up the links associated with a memento to make them more usable.
    Returns a new links dict and does not alter the original.

    Specifically, this updates the URLs of any memento references in a links
    object to URLs using the given mode. The Wayback Machine always returns
    links to the `view` mode version of a memento regardless of what mode it is
    sending the current memento in, but users will usually want links to use
    the same mode as the current memento.

    Parameters
    ----------
    links : dict
    current_mode : str

    Returns
    -------
    dict
    """
    if links is None:
        return {}
    elif not isinstance(links, dict):
        return TypeError(f'links should be a dict, not {type(links)}')

    result = {}
    for key, value in links.items():
        if 'memento' in key:
            try:
                result[key] = {
                    **value,
                    'url': _utils.set_memento_url_mode(value['url'], mode)
                }
            except Exception:
                logger.warn(
                    f'The link "{key}" should have had a memento URL in the '
                    f'`url` field, but instead it was: {value}'
                )
                result[key] = value
        else:
            result[key] = value

    return result


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

    def send(self, method, url, *, params=None, allow_redirects=True, timeout=-1) -> InternalHttpResponse:
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

    # Customize `request` in order to set a default timeout from the session.
    # We can't do this in `send` because `request` always passes a `timeout`
    # keyword to `send`. Inside `send`, we can't tell the difference between a
    # user explicitly requesting no timeout and not setting one at all.
    def request(self, method, url, *, params=None, allow_redirects=True, timeout=-1) -> InternalHttpResponse:
        """
        Perform an HTTP request using this session.
        """
        return self.send(method, url, params=params, allow_redirects=allow_redirects, timeout=timeout)

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


# TODO: add retry, backoff, cross_thread_backoff, and rate_limit options that
# create a custom instance of urllib3.utils.Retry
class WaybackClient(_utils.DepthCountedContext):
    """
    A client for retrieving data from the Internet Archive's Wayback Machine.

    You can use a WaybackClient as a context manager. When exiting, it will
    close the session it's using (if you've passed in a custom session, make
    sure not to use the context manager functionality unless you want to live
    dangerously).

    Parameters
    ----------
    session : WaybackSession, optional
    """
    def __init__(self, session=None):
        self.session: WaybackSession = session or WaybackSession()

    def __exit_all__(self, type, value, traceback):
        self.close()

    def close(self):
        "Close the client's session."
        self.session.close()

    def search(self, url, *, match_type=None, limit=1000, offset=None,
               fast_latest=None, from_date=None, to_date=None,
               filter_field=None, collapse=None, resolve_revisits=True,
               skip_malformed_results=True,
               # Deprecated Parameters
               matchType=None, fastLatest=None, resolveRevisits=None):
        """
        Search archive.org's CDX API for all captures of a given URL. This
        returns an iterator of :class:`CdxRecord` objects. The `StopIteration`
        value is the total count of found captures.

        Results include captures with similar, but not exactly matching URLs.
        They are matched by a SURT-formatted, canonicalized URL that:

        * Does not differentiate between HTTP and HTTPS,
        * Is not case-sensitive, and
        * Treats ``www.`` and ``www*.`` subdomains the same as no subdomain at
          all.

        This will automatically page through all results for a given search. If
        you want fewer results, you can stop iterating early:

        .. code-block:: python

          from itertools import islice
          first10 = list(islice(client.search(...), 10))

        Parameters
        ----------
        url : str
            The URL to search for captures of.

            Special patterns in ``url`` imply a value for the ``match_type``
            parameter and match multiple URLs:

            * If the URL starts with `*.` (e.g. ``*.epa.gov``) OR
              ``match_type='domain'``, the search will include all URLs at the
              given domain and its subdomains.
            * If the URL ends with `/*` (e.g. ``https://epa.gov/*``) OR
              ``match_type='prefix'``, the search will include all URLs that
              start with the text up to the ``*``.
            * Otherwise, this returns matches just for the requeted URL.

        match_type : str, optional
            Determines how to interpret the ``url`` parameter. It must be one of
            the following:

            * ``exact`` (default) returns results matching the requested URL
              (see notes about SURT above; this is not an exact string match of
              the URL you pass in).
            * ``prefix`` returns results that start with the requested URL.
            * ``host`` returns results from all URLs at the host in the
              requested URL.
            * ``domain`` returns results from all URLs at the domain or any
              subdomain of the requested URL.

            The default value is calculated based on the format of ``url``.

        limit : int, default: 1000
            Maximum number of results per request to the API (not the maximum
            number of results this function yields).

            Negative values return the most recent N results.

            Positive values are complicated! The search server will only scan so
            much data on each query, and if it finds fewer than ``limit``
            results before hitting its own internal limits, it will behave as if
            if there are no more results, even though there may be.

            Unfortunately, ideal values for ``limit`` aren't very predicatable
            because the search server combines data from different sources, and
            they do not all behave the same. Their parameters may also be
            changed over time.

            In general…

            * The default value should work well in typical cases.
            * For frequently captured URLs, you may want to set a higher value
              (e.g. 12,000) for more efficient querying.
            * For infrequently captured URLs, you may want to set a lower value
              (e.g. 100 or even 10) to ensure that your query does not hit
              internal limits before returning.
            * For extremely infrequently captured URLs, you may simply want to
              call ``search()`` multiple times with different, close together
              ``from_date`` and ``to_date`` values.

        offset : int, optional
            Skip the first N results.
        fast_latest : bool, optional
            Get faster results when using a negative value for ``limit``. It may
            return a variable number of results that doesn't match the value
            of ``limit``. For example,
            ``search('http://epa.gov', limit=-10, fast_latest=True)`` may return
            any number of results between 1 and 10.
        from_date : datetime or date, optional
            Only include captures after this date. Equivalent to the
            `from` argument in the CDX API. If it does not have a time zone, it
            is assumed to be in UTC.
        to_date : datetime or date, optional
            Only include captures before this date. Equivalent to the `to`
            argument in the CDX API. If it does not have a time zone, it is
            assumed to be in UTC.
        filter_field : str or list of str or tuple of str, optional
            A filter or list of filters for any field in the results. Equivalent
            to the ``filter`` argument in the CDX HTTP API. Format:
            ``[!]field:regex`` or ``~[!]field:substring``, e.g.
            ``'!statuscode:200'`` to select only captures with a non-2xx status
            code, or ``'~urlkey:feature'`` to select only captures where the
            SURT-formatted URL key has "feature" somewhere in it.

            To apply multiple filters, use a list or tuple of strings instead of
            a single string, e.g. ``['statuscode:200', 'urlkey:.*feature.*']``.

            Regexes are matched against the *entire* field value. For example,
            ``'statuscode:2'`` will never match, because all ``statuscode``
            values are three characters. Instead, to match all status codes with
            a "2" in them, use ``'statuscode:.*2.*'``. Add a ``!`` at before the
            field name to negate the match.

            Valid field names are: ``urlkey``, ``timestamp``, ``original``,
            ``mimetype``, ``statuscode``, ``digest``, ``length``.
        collapse : str, optional
            Collapse consecutive results that match on a given field. (format:
            `fieldname` or `fieldname:N` -- N is the number of chars to match.)
        resolve_revisits : bool, default: True
            Attempt to resolve ``warc/revisit`` records to their actual content
            type and response code. Not supported on all CDX servers.
        skip_malformed_results : bool, default: True
            If true, don't yield records that look like they have no actual
            memento associated with them. Some crawlers will erroneously
            attempt to capture bad URLs like
            ``http://mailto:someone@domain.com`` or
            ``http://data:image/jpeg;base64,AF34...`` and so on. This is a
            filter performed client side and is not a CDX API argument.

        Raises
        ------
        UnexpectedResponseFormat
            If the CDX response was not parseable.

        Yields
        ------
        version: CdxRecord
            A :class:`CdxRecord` encapsulating one capture or revisit

        References
        ----------
        * HTTP API Docs: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
        * SURT formatting: http://crawler.archive.org/articles/user_manual/glossary.html#surt
        * SURT implementation: https://github.com/internetarchive/surt

        Notes
        -----
        Several CDX API parameters are not relevant or handled automatically
        by this function. This does not support: `output`, `fl`,
        `showDupeCount`, `showSkipCount`, `lastSkipTimestamp`, `showNumPages`,
        `showPagedIndex`.

        It also does not support `page` and `pageSize` for
        pagination because they work differently from the `resumeKey` method
        this uses, and results do not include recent captures when using them.
        """
        if matchType is not None:
            warn('The `matchType` parameter for search() was renamed to '
                 '`match_type`. Support for the old name will be removed in '
                 'wayback v0.5.0; please update your code.',
                 DeprecationWarning,
                 stacklevel=2)
            match_type = match_type or matchType
        if fastLatest is not None:
            warn('The `fastLatest` parameter for search() was renamed to '
                 '`fast_latest`. Support for the old name will be removed in '
                 'wayback v0.5.0; please update your code.',
                 DeprecationWarning,
                 stacklevel=2)
            fast_latest = fast_latest or fastLatest
        if resolveRevisits is not None:
            warn('The `resolveRevisits` parameter for search() was renamed to '
                 '`resolve_revisits`. Support for the old name will be removed '
                 'in wayback v0.5.0; please update your code.',
                 DeprecationWarning,
                 stacklevel=2)
            resolve_revisits = resolve_revisits or resolveRevisits

        # TODO: Check types (requires major update)
        query_args = {'url': url, 'matchType': match_type, 'limit': limit,
                      'offset': offset, 'from': from_date,
                      'to': to_date, 'filter': filter_field,
                      'fastLatest': fast_latest, 'collapse': collapse,
                      'showResumeKey': True,
                      'resolveRevisits': resolve_revisits}

        query = {}
        for key, value in query_args.items():
            if value is not None:
                if isinstance(value, str):
                    query[key] = value
                elif isinstance(value, (list, tuple)):
                    query[key] = value
                elif isinstance(value, date):
                    query[key] = _utils.format_timestamp(value)
                else:
                    query[key] = str(value).lower()

        next_query = query
        count = 0
        previous_result = None
        while next_query:
            sent_query, next_query = next_query, None
            response = self.session.request('GET', CDX_SEARCH_URL,
                                            params=sent_query)

            # Read/cache the response and close straightaway. If we need
            # to raise an exception based on the response, we want to
            # pre-emptively close it so a user handling the error doesn't need
            # to worry about it. If we don't raise here, we still want to
            # close the connection so it doesn't leak when we move onto
            # the next page of results or when this iterator ends.
            response.close()

            if response.status_code >= 400:
                if 'AdministrativeAccessControlException' in response.text:
                    raise BlockedSiteError(query['url'])
                elif 'RobotAccessControlException' in response.text:
                    raise BlockedByRobotsError(query['url'])
                else:
                    raise WaybackException(f'HTTP {response.status_code} error for CDX search: "{query}"')

            lines = iter(response.content.splitlines())
            logger.warning(f'Unparsed CDX lines: {response.content.splitlines()}')

            for line in lines:
                text = line.decode()

                # The resume key is delineated by a blank line.
                if text == '':
                    next_query = {**query, 'resumeKey': next(lines).decode()}
                    break
                elif text == previous_result:
                    # This result line is a repeat. Skip it.
                    continue
                else:
                    previous_result = text

                try:
                    data = CdxRecord(*text.split(' '), '', '')
                    if data.status_code == '-':
                        # the status code given for a revisit record
                        status_code = None
                    else:
                        status_code = int(data.status_code)
                    length = None if data.length == '-' else int(data.length)
                    capture_time = _utils.parse_timestamp(data.timestamp)
                except Exception as err:
                    if 'RobotAccessControlException' in text:
                        raise BlockedByRobotsError(query["url"])
                    raise UnexpectedResponseFormat(
                        f'Could not parse CDX output: "{text}" (query: {sent_query})') from err

                clean_url = REDUNDANT_HTTPS_PORT.sub(
                    r'\1\2', REDUNDANT_HTTP_PORT.sub(
                        r'\1\2', data.url))
                if skip_malformed_results and is_malformed_url(clean_url):
                    continue
                if clean_url != data.url:
                    data = data._replace(url=clean_url)

                # TODO: repeat captures have a status code of `-` and a mime type
                # of `warc/revisit`. These can only be resolved by requesting the
                # content and following redirects. Maybe nice to do so
                # automatically here.
                data = data._replace(
                    status_code=status_code,
                    length=length,
                    timestamp=capture_time,
                    raw_url=_utils.format_memento_url(
                        url=data.url,
                        timestamp=data.timestamp,
                        mode=Mode.original.value),
                    view_url=_utils.format_memento_url(
                        url=data.url,
                        timestamp=data.timestamp,
                        mode=Mode.view.value)
                )
                count += 1
                yield data

        return count

    def get_memento(self, url, timestamp=None, mode=Mode.original, *,
                    exact=True, exact_redirects=None,
                    target_window=24 * 60 * 60, follow_redirects=True,
                    # Deprecated Parameters
                    datetime=None):
        """
        Fetch a memento (an archived HTTP response) from the Wayback Machine.

        Not all mementos can be successfully fetched (or “played back” in
        Wayback terms). In this case, ``get_memento`` can load the
        next-closest-in-time memento or it will raise
        :class:`wayback.exceptions.MementoPlaybackError` depending on the value
        of the ``exact`` and ``exact_redirects`` parameters (see more details
        below).

        Parameters
        ----------
        url : string or CdxRecord
            URL to retrieve a memento of. This can be any of:

            - A normal URL (e.g. ``http://www.noaa.gov/``). When using this
              form, you must also specify ``timestamp``.
            - A ``CdxRecord`` retrieved from
              :meth:`wayback.WaybackClient.search`.
            - A URL of the memento in Wayback, e.g.
              ``https://web.archive.org/web/20180816111911id_/http://www.noaa.gov/``

        timestamp : datetime.datetime or datetime.date or str, optional
            The time at which to retrieve a memento of ``url``. If ``url`` is
            a :class:`wayback.CdxRecord` or full memento URL, this parameter
            can be omitted.
        mode : wayback.Mode or str, default: wayback.Mode.original
            The playback mode of the memento. This determines whether the
            content of the returned memento is exactly as originally captured
            (the default) or modified in some way. See :class:`wayback.Mode`
            for a description of possible values.

            For more details, see:
            https://archive-access.sourceforge.net/projects/wayback/administrator_manual.html#Archival_URL_Replay_Mode

        exact : boolean, default: True
            If false and the requested memento either doesn't exist or can't be
            played back, this returns the closest-in-time memento to the
            requested one, so long as it is within ``target_window``. If there
            was no memento in the target window or if ``exact=True``, then this
            will raise :class:`wayback.exceptions.MementoPlaybackError`.
        exact_redirects : boolean, optional
            If false and the requested memento is a redirect whose *target*
            doesn't exist or can't be played back, this returns the
            closest-in-time memento to the intended target, so long as it is
            within ``target_window``. If unset, this will be the same as
            ``exact``.
        target_window : int, default: 86400
            If the memento is of a redirect, allow up to this many seconds
            between the capture of the redirect and the capture of the
            redirect's target URL. This window also applies to the first
            memento if ``exact=False`` and the originally
            requested memento was not available.
            Defaults to 86,400 (24 hours).
        follow_redirects : boolean, default: True
            If true (the default), ``get_memento`` will follow historical
            redirects to return the content that a web browser would have
            ultimately displayed at the requested URL and time, rather than the
            memento of an HTTP redirect response (i.e. a 3xx status code).
            That is, if ``http://example.com/a`` redirected to
            ``http://example.com/b``, then this method returns the memento for
            ``/a`` when ``follow_redirects=False`` and the memento for ``/b``
            when ``follow_redirects=True``.

        Returns
        -------
        Memento
            A :class:`Memento` object with information about the archived HTTP
            response.
        """
        if datetime:
            warn('The `datetime` parameter for get_memento() was renamed to '
                 '`timestamp`. Support for the old name will be removed '
                 'in wayback v0.5.0; please update your code.',
                 DeprecationWarning,
                 stacklevel=2)
            timestamp = timestamp or datetime

        if exact_redirects is None:
            exact_redirects = exact

        # Convert Mode enum values to strings rather than the other way around.
        # There is a very real possibility of other undocumented modes and we
        # don't want converting them via `Mode(str_value)` to raise an error
        # and make them impossible to use. Wayback folks have been unclear
        # about exactly what all the options are, and it sounds kind of like
        # this is an old and kind of messy part of the codebase, where things
        # may have been changed around a few times and the people who worked on
        # it are now off doing other things.
        if isinstance(mode, Mode):
            mode = mode.value
        elif not isinstance(mode, str):
            raise TypeError('`mode` must be a wayback.Mode or string '
                            f'(received {mode!r})')

        if isinstance(url, CdxRecord):
            original_date = url.timestamp
            original_url = url.url
        else:
            try:
                original_url, original_date, mode = _utils.memento_url_data(url)
            except ValueError:
                original_url = url
                if not timestamp:
                    raise TypeError('You must specify `timestamp` when using a '
                                    'normal URL for get_memento()')
                else:
                    original_date = _utils.ensure_utc_datetime(timestamp)

        original_date_wayback = _utils.format_timestamp(original_date)
        url = _utils.format_memento_url(url=original_url,
                                        timestamp=original_date_wayback,
                                        mode=mode)

        # Correctly following redirects is actually pretty complicated. In
        # the simplest case, a memento is a simple web page, and that's
        # no problem. However...
        #   1.  If the response was a >= 400 status, we have to determine
        #       whether that status is coming from the memento or from the
        #       the Wayback Machine itself.
        #   2.  If the response was a 3xx status (a redirect) we have to
        #       determine the same thing, but it's a little more complex...
        #       a) If the redirect *is* the memento, its target may be an
        #          actual memento (see #1) or it may be a redirect (#2).
        #          The targeted URL is frequently captured anywhere from
        #          the same second to a few hours later, so it is likely
        #          the target will result in case 2b (below).
        #       b) If there is no memento for the requested time, but there
        #          are mementos for the same URL at another time, Wayback
        #          *may* redirect to that memento.
        #          - If this was on the original request, that's *not* ok
        #            because it means we're getting a different memento
        #            than we asked for.
        #          - If the redirect came from a URL that was the target of
        #            of a memento redirect (2a), then this is expected.
        #            Before following the redirect, though, we first sanity
        #            check it to make sure the memento we are redirecting
        #            to actually came from nearby in time (sometimes
        #            Wayback will redirect to captures *months* away).
        history = []
        debug_history = []
        urls = set()
        previous_was_memento = False

        response = self.session.request('GET', url, allow_redirects=False)
        protocol_and_www = re.compile(r'^https?://(www\d?\.)?')
        memento = None
        while True:
            current_url, current_date, current_mode = _utils.memento_url_data(response.url)

            # In view mode, redirects need special handling.
            if current_mode == Mode.view.value:
                redirect_url = detect_view_mode_redirect(response, current_date)
                if redirect_url:
                    # Fix up response properties to be like other modes.
                    # redirect = requests.Request('GET', redirect_url)
                    # response._next = self.session.prepare_request(redirect)
                    # XXX: make this publicly settable?
                    response._redirect_url = redirect_url
                    response.headers['Memento-Datetime'] = current_date.strftime(
                        '%a, %d %b %Y %H:%M:%S %Z'
                    )

            is_memento = is_memento_response(response)

            # A memento URL will match possible captures based on its SURT
            # form, which means we might be getting back a memento captured
            # from a different URL than the one specified in the request.
            # If present, the `original` link will be the *captured* URL.
            if response.links and ('original' in response.links):
                current_url = response.links['original']['url']

            if is_memento:
                links = clean_memento_links(response.links, mode)
                memento = Memento(url=current_url,
                                  timestamp=current_date,
                                  mode=current_mode,
                                  memento_url=response.url,
                                  status_code=response.status_code,
                                  headers=Memento.parse_memento_headers(response.headers, response.url),
                                  encoding=response.encoding,
                                  raw=response,
                                  raw_headers=response.headers,
                                  links=links,
                                  history=history,
                                  debug_history=debug_history)
                if not follow_redirects:
                    break
            else:
                memento = None
                # The exactness requirements for redirects from memento
                # playbacks and non-playbacks is different -- even with
                # strict matching, a memento that redirects to a non-
                # memento is normal and ok; the target of a redirect will
                # rarely have been captured at the same time as the
                # redirect itself. (See 2b)
                playable = False
                if response.redirect_url and (
                    (len(history) == 0 and not exact) or
                    (len(history) > 0 and (previous_was_memento or not exact_redirects))
                ):
                    target_url, target_date, _ = _utils.memento_url_data(response.redirect_url)
                    # A non-memento redirect is generally taking us to the
                    # closest-in-time capture of the same URL. Note that is
                    # NOT the next capture -- i.e. the one that would have
                    # been produced by an earlier memento redirect -- it's
                    # just the *closest* one. The first job here is to make
                    # sure it fits within our target window.
                    if abs(target_date - original_date).total_seconds() <= target_window:
                        # The redirect will point to the closest-in-time
                        # SURT URL, which will often not be an exact URL
                        # match. If we aren't looking for exact matches,
                        # then just assume wherever we're redirecting to is
                        # ok. Otherwise, try to sanity-check the URL.
                        if exact_redirects:
                            # FIXME: what should *really* happen here, if
                            # we want exactness, is a CDX search for the
                            # next-int-time capture of the exact URL we
                            # redirected to. I'm not totally sure how
                            # great that is (also it seems high overhead to
                            # do a search in the middle of this series of
                            # memento lookups), so just do a loose URL
                            # check for now.
                            current_nice_url = protocol_and_www.sub('', current_url).casefold()
                            target_nice_url = protocol_and_www.sub('', target_url).casefold()
                            playable = current_nice_url == target_nice_url
                        else:
                            playable = True

                if not playable:
                    response.close()
                    message = response.headers.get('X-Archive-Wayback-Runtime-Error', '')
                    if (
                        ('AdministrativeAccessControlException' in message) or
                        ('URL has been excluded' in response.text)
                    ):
                        raise BlockedSiteError(f'{url} is blocked from access')
                    elif (
                        ('RobotAccessControlException' in message) or
                        ('robots.txt' in response.text)
                    ):
                        raise BlockedByRobotsError(f'{url} is blocked by robots.txt')
                    elif message:
                        raise MementoPlaybackError(f'Memento at {url} could not be played: {message}')
                    elif response.is_success:
                        # TODO: Raise more specific errors for the possible
                        # cases here. We *should* only arrive here when
                        # there's a redirect and:
                        # - `exact` is true.
                        # - `exact_redirects` is true and the redirect was
                        #   not exact.
                        # - The target URL is outside `target_window`.
                        raise MementoPlaybackError(f'Memento at {url} could not be played')
                    elif response.status_code == 404:
                        raise NoMementoError(f'The URL {url} has no mementos and was never archived')
                    else:
                        raise MementoPlaybackError(f'{response.status_code} error while loading '
                                                   f'memento at {url}')

            if response.redirect_url:
                previous_was_memento = is_memento
                response.close()

                # Wayback sometimes has circular memento redirects ¯\_(ツ)_/¯
                urls.add(response.url)
                if response.redirect_url in urls:
                    raise MementoPlaybackError(f'Memento at {url} is circular')

                # All requests are included in `debug_history`, but
                # `history` only shows redirects that were mementos.
                debug_history.append(response.url)
                if is_memento:
                    history.append(memento)
                response = self.session.request('GET', response.redirect_url, allow_redirects=False)
            else:
                break

        return memento
