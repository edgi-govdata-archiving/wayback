"""
HTTP tooling used by Wayback when making requests to and handling responses
from Wayback Machine servers.
"""

import logging
import threading
from typing import Optional, Tuple, Union
from urllib.parse import urljoin
import requests
from requests.exceptions import (ChunkedEncodingError,
                                 ContentDecodingError)
from urllib3.connectionpool import HTTPConnectionPool

logger = logging.getLogger(__name__)

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
    Handles making actual HTTP requests over the network. For now, this is an
    implementation detail, but it may be a way for users to customize behavior
    in the future.
    """

    def __init__(self) -> None:
        self._session = requests.Session()

    # FIXME: remove `allow_redirects`! Redirection needs to be handled by
    # whatever does throttling, which is currently not here.
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict = None,
        headers: dict = None,
        allow_redirects: bool = True,
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
        allow_redirects : bool, default: True
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
        response = self._session.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            allow_redirects=allow_redirects,
            timeout=timeout
        )
        return WaybackRequestsResponse(response)

    def close(self):
        self._session.close()
