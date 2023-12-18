"""
HTTP tooling used by Wayback when making requests and handling responses.
"""

import re
from typing import Generator, Optional
from urllib.parse import urlencode, urljoin
from urllib3 import HTTPResponse
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import (DecodeError,
                                ProtocolError)
# The Header dict lives in a different place for urllib3 v2:
try:
    from urllib3 import HTTPHeaderDict as Urllib3HTTPHeaderDict
# vs. urllib3 v1:
except ImportError:
    from urllib3.response import HTTPHeaderDict as Urllib3HTTPHeaderDict


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
