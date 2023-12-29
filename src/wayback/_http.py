"""
HTTP tooling used by Wayback when making requests to and handling responses
from Wayback Machine servers.
"""

import logging
import threading
from typing import Optional
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


# FIXME: This implementation is tied to requests. It should probably be an
# abstract base class and we should have a requests-specific implementation,
# which would make `WaybackHttpAdapter` customizable/pluggable.
class InternalHttpResponse:
    """
    Internal wrapper class for HTTP responses. _This should never be exposed to
    user code_; it's job is to insulate the rest of the Wayback package from
    the particulars of the underlying HTTP tooling (e.g. requests, httpx, etc).
    This is *similar* to response objects from httpx and requests, although it
    lacks facilities from those libraries that we don't need or use, and takes
    shortcuts that are specific to our use cases.
    """
    status_code: int
    headers: dict
    encoding: Optional[str] = None
    url: str
    links: dict
    _read_lock: threading.Lock
    _raw: requests.Response
    _content: Optional[bytes] = None
    _redirect_url: Optional[str] = None

    def __init__(self, raw: requests.Response, request_url: str) -> None:
        self._read_lock = threading.Lock()
        self._raw = raw
        self.status_code = raw.status_code
        self.headers = raw.headers
        self.url = urljoin(request_url, getattr(raw, 'url', ''))
        self.encoding = raw.encoding
        self.links = raw.links

    @property
    def redirect_url(self) -> str:
        """
        The URL this response redirects to. If the response is not a redirect,
        this returns an empty string.
        """
        if self.status_code >= 300 and self.status_code < 400:
            location = self.headers.get('location')
            if location:
                return urljoin(self.url, location)

        return ''

    @property
    def is_success(self) -> bool:
        return self.status_code >= 200 and self.status_code < 300

    @property
    def content(self) -> bytes:
        with self._read_lock:
            if self._content is None:
                # TODO: This is designed around the requests library and is not
                # generic enough. A better version would either:
                # 1. Leave this for subclasses to implement.
                # 2. Read iteratively from a `raw` object with a `read(n)` method.
                self._content = self._raw.content

            return self._content

    @property
    def text(self) -> str:
        encoding = self.encoding or self.sniff_encoding() or 'utf-8'
        try:
            return str(self.content, encoding, errors="replace")
        except (LookupError, TypeError):
            return str(self.content, errors="replace")

    def sniff_encoding(self) -> None:
        self.content
        return self._raw.apparent_encoding

    # XXX: This needs wrapping with a lock! (Maybe `_read_lock` should be an
    # RLock so it can be used both here and in `content`).
    def close(self, cache: bool = True) -> None:
        """
        Read the rest of the response off the wire and release the connection.
        If the full response is not read, the connection can hang and programs
        will leak memory (and cause a bad time for the server as well).

        Parameters
        ----------
        cache : bool, default: True
            Whether to cache the response body so it can still be used via the
            ``content`` and ``text`` properties.
        """
        if self._raw:
            try:
                # TODO: if cache is false, it would be better not to try and
                # read content at all.
                self.content
                if not cache:
                    self._content = ''
            except (ChunkedEncodingError, ContentDecodingError, RuntimeError):
                with self._read_lock:
                    self._raw.read(decode_content=False)
            finally:
                with self._read_lock:
                    self._raw.close()


class WaybackHttpAdapter:
    """
    TODO
    """

    def __init__(self) -> None:
        self._session = requests.Session()

    def request(
        self,
        method,
        url,
        *,
        params=None,
        headers=None,
        allow_redirects=True,
        timeout=None
    ) -> InternalHttpResponse:
        response = self._session.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            allow_redirects=allow_redirects,
            timeout=timeout
        )
        return InternalHttpResponse(response, url)

    def close(self):
        self._session.close()
