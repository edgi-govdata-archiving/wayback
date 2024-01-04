"""
HTTP tooling used by Wayback when making requests to and handling responses
from Wayback Machine servers.
"""

import logging
from numbers import Real
import threading
import time
from typing import Dict, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse
import requests
from requests.exceptions import (ChunkedEncodingError,
                                 ConnectionError,
                                 ContentDecodingError,
                                 ProxyError,
                                 RetryError,
                                 Timeout)
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import (ConnectTimeoutError,
                                MaxRetryError,
                                ReadTimeoutError)
from . import __version__
from ._utils import DisableAfterCloseAdapter, RateLimit, parse_retry_after
from .exceptions import RateLimitError, WaybackRetryError

logger = logging.getLogger(__name__)

# Global default rate limits for various endpoints. Internet Archive folks have
# asked us to set the defaults at 80% of the hard limits.
DEFAULT_CDX_RATE_LIMIT = RateLimit(0.8 * 60 / 60)
DEFAULT_TIMEMAP_RATE_LIMIT = RateLimit(0.8 * 100 / 60)
DEFAULT_MEMENTO_RATE_LIMIT = RateLimit(0.8 * 600 / 60)

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
    class WaybackUrllib3Response(HTTPConnectionPool.ResponseCls):
        @classmethod
        def from_httplib(cls, httplib_response, **response_kwargs):
            headers = httplib_response.msg
            pairs = headers.items()
            if ('content-encoding', '') in pairs and ('Content-Encoding', 'gzip') in pairs:
                del headers['content-encoding']
                headers['Content-Encoding'] = 'gzip'
            return super().from_httplib(httplib_response, **response_kwargs)

    HTTPConnectionPool.ResponseCls = WaybackUrllib3Response
else:
    # urllib3 v2.x:
    #
    # Unfortunately, we can't wrap the `HTTPConnection.getresponse` method in
    # urllib3 v2, since it may have read the response body before returning. So
    # we patch the HTTPHeaderDict class instead.
    from urllib3._collections import HTTPHeaderDict as Urllib3HTTPHeaderDict
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


class WaybackHttpResponse:
    """
    Represents an HTTP response from a server. This might be included as an
    attribute of an exception, but should otherwise not be exposed to user
    code in normal circumstances. It's meant to wrap to provide a standard,
    thread-safe interface to response objects from whatever underlying HTTP
    tool is being used (e.g. requests, httpx, etc.).
    """
    status_code: int
    headers: dict
    encoding: Optional[str] = None
    url: str
    links: dict

    def __init__(self, url: str, status_code: int, headers: dict, links: dict = None, encoding: str = None):
        self.url = url
        self.status_code = status_code
        self.headers = headers
        self.links = links or {}
        self.encoding = encoding

    @property
    def redirect_url(self) -> str:
        """
        The absolute URL this response redirects to. It will always be a
        complete URL with a scheme and host. If the response is not a redirect,
        this returns an empty string.
        """
        if self.status_code >= 300 and self.status_code < 400:
            location = self.headers.get('location')
            if location:
                return urljoin(self.url, location)

        return ''

    @property
    def is_success(self) -> bool:
        """Whether the status code indicated success (2xx) or an error."""
        return self.status_code >= 200 and self.status_code < 300

    @property
    def is_memento(self) -> bool:
        return 'Memento-Datetime' in self.headers

    @property
    def content(self) -> bytes:
        """
        The response body as bytes. This is the *decompressed* bytes, so
        responses with `Content-Encoding: gzip` will be unzipped here.
        """
        raise NotImplementedError()

    @property
    def text(self) -> str:
        """
        Gets the response body as a text string. it will try to decode the raw
        bytes of the response based on response's declared encoding (i.e. from
        the ``Content-Type`` header), falling back to sniffing the encoding or
        using UTF-8.
        """
        encoding = self.encoding or self.sniff_encoding() or 'utf-8'
        try:
            return str(self.content, encoding, errors="replace")
        except (LookupError, TypeError):
            return str(self.content, errors="replace")

    def sniff_encoding(self) -> Optional[str]:
        """
        Sniff the text encoding from the raw bytes of the content, if possible.
        """
        return None

    def close(self, cache: bool = True) -> None:
        """
        Read the rest of the response off the wire and release the connection.
        If the full response is not read, the connection can hang and waste
        both local and server resources.

        Parameters
        ----------
        cache : bool, default: True
            Whether to cache the response body so it can still be used via the
            ``content`` and ``text`` properties.
        """
        raise NotImplementedError()


class WaybackRequestsResponse(WaybackHttpResponse):
    """
    Wraps an HTTP response from the requests library.
    """
    _read_lock: threading.RLock
    _raw: requests.Response
    _content: Optional[bytes] = None

    def __init__(self, raw: requests.Response) -> None:
        # NOTE: if we drop down to urllib3, we need the requested URL to be
        # passed in so we can join it with the response's URL (in urllib3,
        # `response.url` does not include the scheme/host/etc data that belongs
        # to the connection pool).
        super().__init__(
            url=raw.url,
            status_code=raw.status_code,
            headers=raw.headers,
            links=raw.links,
            encoding=raw.encoding
        )
        self._read_lock = threading.RLock()
        self._raw = raw

    @property
    def content(self) -> bytes:
        with self._read_lock:
            if self._content is None:
                self._content = self._raw.content

            return self._content

    def sniff_encoding(self) -> None:
        self.content
        return self._raw.apparent_encoding

    def close(self, cache: bool = True) -> None:
        with self._read_lock:
            # Reading bytes potentially involves decoding data from compressed
            # gzip/brotli/etc. responses, so we need to handle those errors by
            # continuing to just read the raw data off the socket instead.
            #
            # This fallback behavior is inspired by requests:
            #   https://github.com/psf/requests/blob/eedd67462819f8dbf8c1c32e77f9070606605231/requests/sessions.py#L160-L163
            # For urllib3, the appropriate errors to handle would be:
            #   `(DecodeError, ProtocolError, RuntimeError)`
            try:
                if cache:
                    try:
                        self.content
                    except (ChunkedEncodingError, ContentDecodingError, RuntimeError):
                        self._raw.raw.read(decode_content=False)
                else:
                    self._raw.raw.read(decode_content=False)
            finally:
                self._raw.close()


class WaybackHttpAdapter:
    """
    Handles making actual HTTP requests over the network. This is an abstract
    base class that defines the API an adapter must implement.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict = None,
        headers: dict = None,
        follow_redirects: bool = True,
        timeout: Union[int, Tuple[int, int]] = None
    ) -> WaybackHttpResponse:
        """
        Send an HTTP request and return a :class:`WaybackHttpResponse` object
        representing the response.

        Parameters
        ----------
        method : str
            Method to use for the request, e.g. ``'GET'``, ``'POST'``.
        url : str
            The URL to reqeust.
        params : dict, optional
            For POST/PUT requests, data to be encoded in the response body. For
            other methods, this should be encoded as the querystring.
        headers : dict, optional
            The HTTP headers to send with the request.
        follow_redirects : bool, default: True
            Whether to follow redirects before returning a response.
        timeout : int or float or tuple of (int or float, int or float), optional
            How long to wait, in seconds, before timing out. If this is a single
            number, it will be used as both a connect timeout (how long to wait
            for the first bit of response data) and a read timeout (how long
            to wait between bits of response data). If a tuple, the values will
            be used as the connect and read timeouts, respectively.

        Returns
        -------
        WaybackHttpResponse
        """
        raise NotImplementedError()

    def close(self) -> None:
        """
        Close the adapter and release any long-lived resources, like pooled
        HTTP connections.
        """
        ...


class RequestsAdapter(WaybackHttpAdapter):
    """
    Wrap the requests library for making HTTP requests.
    """

    def __init__(self) -> None:
        self._session = requests.Session()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict = None,
        headers: dict = None,
        follow_redirects: bool = True,
        timeout: Union[int, Tuple[int, int]] = None
    ) -> WaybackHttpResponse:
        logger.debug('Sending HTTP request <%s "%s">', method, url)
        response = self._session.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            allow_redirects=follow_redirects,
            timeout=timeout
        )
        return WaybackRequestsResponse(response)

    def close(self) -> None:
        self._session.close()


class RetryAndRateLimitAdapter(WaybackHttpAdapter):
    """
    Adds rate limiting and retry functionality to an HTTP adapter. This class
    can't actually make HTTP requests and should usually be used in a
    multiple-inheritance situation. Alternatively, you can override the
    ``request_raw()`` method.

    Parameters
    ----------
    retries : int, default: 6
        The maximum number of retries for failed HTTP requests.
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
    rate_limits : dict of (str, RateLimit)
        The rate limits that should be applied to different URL paths. The keys
        are URL path prefixes, e.g. ``"/cdx/search/"``, and the values are
        :class:`wayback.RateLimit` objects. When requests are made, the rate
        limit from the most specific matching path is used and execution will
        pause to ensure the rate limit is not exceeded.


    Examples
    --------

    Usage via multiple inheritance:

    >>> class CombinedAdapter(RetryAndRateLimitAdapter, SomeActualHttpAdapterWithoutRateLimits):
    >>>     ...

    Usage via override:

    >>> class MyHttpAdapter(RetryAndRateLimitAdapter):
    >>>     def request_raw(
    >>>         self,
    >>>         method: str,
    >>>         url: str,
    >>>         *,
    >>>         params: dict = None,
    >>>         headers: dict = None,
    >>>         follow_redirects: bool = True,
    >>>         timeout: Union[int, Tuple[int, int]] = None
    >>>     ) -> WaybackHttpResponse:
    >>>         response = urllib.urlopen(...)
    >>>         return make_response_from_urllib(response)
    """

    rate_limits: Dict[str, RateLimit]

    # It seems Wayback sometimes produces 500 errors for transient issues, so
    # they make sense to retry here. Usually not in other contexts, though.
    retryable_statuses = frozenset((413, 421, 500, 502, 503, 504, 599))

    # XXX: Some of these are requests-specific and should move WaybackRequestsAdapter.
    retryable_errors = (ConnectTimeoutError, MaxRetryError, ReadTimeoutError,
                        ProxyError, RetryError, Timeout)
    # Handleable errors *may* be retryable, but need additional logic beyond
    # just the error type. See `should_retry_error()`.
    handleable_errors = (ConnectionError,) + retryable_errors

    def __init__(
        self,
        retries: int = 6,
        backoff: Real = 2,
        rate_limits: Dict[str, RateLimit] = {}
    ) -> None:
        super().__init__()
        self.retries = retries
        self.backoff = backoff
        # Sort rate limits by longest path first, so we always match the most
        # specific path when looking for the right rate limit on any given URL.
        self.rate_limits = {path: rate_limits[path]
                            for path in sorted(rate_limits.keys(),
                                               key=lambda k: len(k),
                                               reverse=True)}

    # The implementation of different features is split up by method here, so
    # `request()` calls down through a stack of overrides:
    #
    #   request                        (ensure valid types/values/etc.)
    #   └> _request_redirectable       (handle redirects)
    #      └> _request_retryable       (handle retries for errors)
    #         └> _request_rate_limited (handle rate limiting/throttling)
    #            └> request_raw        (handle actual HTTP)
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict = None,
        headers: dict = None,
        follow_redirects: bool = True,
        timeout: Union[int, Tuple[int, int]] = None
    ) -> WaybackHttpResponse:
        return self._request_redirectable(method,
                                          url,
                                          params=params,
                                          headers=headers,
                                          follow_redirects=follow_redirects,
                                          timeout=timeout)

    def _request_redirectable(self, *args, follow_redirects: bool = True, **kwargs) -> WaybackHttpResponse:
        # FIXME: this method should implement redirect following (if
        # `follow_redirects` is true), rather than passing it to the underlying
        # implementation, since redirects need to be rate limited.
        return self._request_retryable(*args, follow_redirects=follow_redirects, **kwargs)

    def _request_retryable(self, method: str, url: str, **kwargs) -> WaybackHttpResponse:
        start_time = time.time()
        maximum = self.retries
        retries = 0

        while True:
            retry_delay = 0
            try:
                response = self._request_rate_limited(method, url, **kwargs)
                retry_delay = self.get_retry_delay(retries, response)

                if retries >= maximum or not self.should_retry(response):
                    if response.status_code == 429:
                        response.close()
                        raise RateLimitError(response, retry_delay)
                    return response
                else:
                    logger.debug('Received error response (status: %s), will retry', response.status_code)
                    response.close(cache=False)
            except self.handleable_errors as error:
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

    def _request_rate_limited(self, method: str, url: str, **kwargs) -> WaybackHttpResponse:
        parsed_url = urlparse(url)
        for path, limit in self.rate_limits.items():
            if parsed_url.path.startswith(path):
                rate_limit = limit
                break
        else:
            rate_limit = DEFAULT_MEMENTO_RATE_LIMIT

        rate_limit.wait()
        return self.request_raw(method, url, **kwargs)

    def request_raw(self, *args, **kwargs) -> WaybackHttpResponse:
        return super().request(*args, **kwargs)

    def should_retry(self, response: WaybackHttpResponse):
        # A memento may actually be a capture of an error, so don't retry it :P
        if response.is_memento:
            return False

        return response.status_code in self.retryable_statuses

    def should_retry_error(self, error):
        if isinstance(error, self.retryable_errors):
            return True
        elif isinstance(error, ConnectionError):
            # ConnectionErrors from requests actually wrap a whole family of
            # more detailed errors from urllib3, so we need to do some string
            # checking to determine whether the error is retryable.
            text = str(error)
            # NOTE: we have also seen this, which may warrant retrying:
            # `requests.exceptions.ConnectionError: ('Connection aborted.',
            # RemoteDisconnected('Remote end closed connection without
            # response'))`
            if 'NewConnectionError' in text or 'Max retries' in text:
                return True

        return False

    def get_retry_delay(self, retries, response=None):
        delay = 0

        # As of 2023-11-27, the Wayback Machine does not set a `Retry-After`
        # header, so this parsing is really just future-proofing.
        if response is not None:
            delay = parse_retry_after(response.headers.get('Retry-After')) or delay
            if response.status_code == 429 and delay == 0:
                delay = DEFAULT_RATE_LIMIT_DELAY

        # No default backoff on the first retry.
        if retries > 0:
            delay = max(self.backoff * 2 ** (retries - 1), delay)

        return delay


class WaybackRequestsAdapter(RetryAndRateLimitAdapter, DisableAfterCloseAdapter, RequestsAdapter):
    def __init__(
        self,
        retries: int = 6,
        backoff: Real = 2,
        timeout: Union[Real, Tuple[Real, Real]] = 60,
        user_agent: str = None,
        memento_rate_limit: Union[RateLimit, Real] = DEFAULT_MEMENTO_RATE_LIMIT,
        search_rate_limit: Union[RateLimit, Real] = DEFAULT_CDX_RATE_LIMIT,
        timemap_rate_limit: Union[RateLimit, Real] = DEFAULT_TIMEMAP_RATE_LIMIT,
    ) -> None:
        super().__init__(
            retries=retries,
            backoff=backoff,
            rate_limits={
                '/web/timemap': RateLimit.make_limit(timemap_rate_limit),
                '/cdx': RateLimit.make_limit(search_rate_limit),
                # The memento limit is actually a generic Wayback limit.
                '/': RateLimit.make_limit(memento_rate_limit),
            }
        )
        self.timeout = timeout
        self.headers = {
            'User-Agent': (user_agent or
                           f'wayback/{__version__} (+https://github.com/edgi-govdata-archiving/wayback)'),
            'Accept-Encoding': 'gzip, deflate'
        }

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict = None,
        headers: dict = None,
        follow_redirects: bool = True,
        timeout: Union[int, Tuple[int, int]] = -1
    ) -> WaybackHttpResponse:
        timeout = self.timeout if timeout is -1 else timeout
        headers = (headers or {}) | self.headers

        return super().request(method,
                               url,
                               params=params,
                               headers=headers,
                               follow_redirects=follow_redirects,
                               timeout=timeout)
