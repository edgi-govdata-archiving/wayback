from collections import namedtuple
from urllib.parse import urljoin
from ._utils import memento_url_data


CdxRecord = namedtuple('CdxRecord', (
    # Raw CDX values
    'key',
    'timestamp',
    'url',
    'mime_type',
    'status_code',
    'digest',
    'length',
    # Synthesized values
    'raw_url',
    'view_url'
))
"""
Item from iterable of results returned by :meth:`WaybackClient.search`

These attributes contain information provided directly by CDX.

.. py:attribute:: digest

   Content hashed as a base 32 encoded SHA-1.

.. py:attribute:: key

   SURT-formatted URL

.. py:attribute:: length

   Size of captured content in bytes, such as :data:`2767`. This may be
   inaccurate. If the record is a "revisit record", indicated by MIME type
   :data:`'warc/revisit'`, the length seems to be the length of the reference,
   not the length of the content itself.

.. py:attribute:: mime_type

   MIME type of record, such as :data:`'text/html'`, :data:`'warc/revisit'` or
   :data:`'unk'` ("unknown") if this information was not captured.

.. py:attribute:: status_code

   Status code returned by the server when the record was captured, such as
   :data:`200`. This is may be :data:`None` if the record is a revisit record.

.. py:attribute:: timestamp

   The capture time represented as a :class:`datetime.datetime`, such as
   :data:`datetime.datetime(1996, 12, 31, 23, 58, 47, tzinfo=timezone.utc)`.

.. py:attribute:: url

   The URL that was captured by this record, such as
   :data:`'http://www.nasa.gov/'`.

And these attributes are synthesized from the information provided by CDX.

.. py:attribute:: raw_url

   The URL to the raw captured content, such as
   :data:`'http://web.archive.org/web/19961231235847id_/http://www.nasa.gov/'`.

.. py:attribute:: view_url

   The URL to the public view on Wayback Machine. In this view, the links and
   some subresources in the document are rewritten to point to Wayback URLs.
   There is also a navigation panel around the content. Example URL:
   :data:`'http://web.archive.org/web/19961231235847/http://www.nasa.gov/'`.
"""


# NOTE: We use `py:attribute::` listings instead of the standard Numpy
# "Attributes" section (which is formatted like function parameters) because it
# doesn't do a great job of handling properties. See this issue:
# https://github.com/numpy/numpydoc/issues/299
class Memento:
    """
    Represents a memento (an archived HTTP response). This object is similar to
    a response object from the popular "Requests" package, although it has some
    differences designed to differentiate historical information vs. current
    metadata about the stored memento (for example, the ``headers`` attribute
    lists the headers recorded in the memento, and does not include additional
    headers that provide metadata about the Wayback Machine).

    Note that, like an HTTP response, this object represents a potentially open
    network connection to the Wayback Machine. Reading the ``content`` or
    ``text`` attributes will read all the data being received and close the
    connection automatically, but if you do not read those properties, you must
    make sure to call ``close()`` to close to connection. Alternatively, you
    can use a Memento as a context manager. The connection will be closed for
    you when the context ends:

        >>> with a_memento:
        >>>     do_something()
        >>> # Connection is automatically closed here.

    **Fields**

    .. py:attribute:: encoding
        :type: str

        The text encoding of the response, e.g. ``'utf-8'``.

    .. py:attribute:: headers
        :type: dict

        A dict representing the headers of the archived HTTP response. The keys
        are case-sensitive.

    .. py:attribute:: history
        :type: tuple[wayback.Memento]

        A list of :class:`wayback.Memento` objects that were redirects and were
        followed to produce this memento.

    .. py:attribute:: debug_history
        :type: tuple[str]

        List of all URLs redirects followed in order to produce this memento.
        These are "memento URLs" -- that is, they are absolute URLs to the
        Wayback machine like
        ``http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/``,
        rather than URLs of captured redirects, like ``http://www.noaa.gov``.
        Many of the URLs in this list do not represent actual mementos.

    .. py:attribute:: status_code
        :type: int

        The HTTP status code of the archived HTTP response.

    .. py:attribute:: mode
        :type: str

        The playback mode used to produce the Memento.

    .. py:attribute:: timestamp
        :type: datetime.datetime

        The time the memento was originally captured. This includes ``tzinfo``,
        and will always be in UTC.

    .. py:attribute:: url
        :type: str

        The URL that the memento represents, e.g. ``http://www.noaa.gov``.

    .. py:attribute:: memento_url
        :type: str

        The URL at which the memento was fetched from the Wayback Machine, e.g.
        ``http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/``.

    .. py:attribute:: ok
        :type: bool

        Whether the response had an non-error status (i.e. < 400).

    .. py:attribute:: is_redirect
        :type: bool

        Whether the response was a redirect (i.e. had a 3xx status).

    .. py:attribute:: content
        :type: bytes

        The body of the archived HTTP response in bytes.

    .. py:attribute:: text
        :type: str

        The body of the archived HTTP response decoded as a string.
    """

    def __init__(self, *, url, timestamp, mode, memento_url, status_code,
                 headers, encoding, raw, raw_headers, history, debug_history):
        self.url = url
        self.timestamp = timestamp
        self.mode = mode
        self.memento_url = memento_url
        self.status_code = status_code
        self.headers = headers
        self.encoding = encoding
        self._raw = raw
        self._raw_headers = raw_headers

        # Ensure we have non-mutable copies of history info.
        self.history = tuple(history)
        self.debug_history = tuple(debug_history)

    @property
    def ok(self):
        """
        Whether the response had an non-error status (i.e. < 400).

        Returns
        -------
        boolean
        """
        return self.status_code < 400

    @property
    def is_redirect(self):
        """
        Whether the response was a redirect (i.e. had a 3xx status).

        Returns
        -------
        boolean
        """
        return self.ok and self.status_code >= 300

    @property
    def content(self):
        """
        The body of the archived HTTP response in bytes.

        Returns
        -------
        bytes
        """
        return self._raw.content

    @property
    def text(self):
        """
        The body of the archived HTTP response decoded as a string.

        Returns
        -------
        str
        """
        return self._raw.text

    def close(self):
        """
        Close the HTTP response for this Memento. This happens automatically if
        you read ``content`` or ``text``, and if you use the memento as a
        context manager. This method is always safe to call -- it does nothing
        if the response has already been closed.
        """
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @classmethod
    def parse_memento_headers(cls, raw_headers, url='http://web.archive.org/'):
        """
        Extract historical headers from the Memento HTTP response's headers.

        Parameters
        ----------
        raw_headers : dict
            A dict of HTTP headers from the Memento's HTTP response.
        url : str, optional
            The URL of the resource the headers are being parsed for. It's used
            when header data contains relative/incomplete URL information.

        Returns
        -------
        dict
        """
        # Archived, historical headers are all reproduced as headers in the
        # memento response, but start with "X-Archive-Orig-".
        prefix = 'X-Archive-Orig-'
        headers = {
            key[len(prefix):]: value for key, value in raw_headers.items()
            if key.startswith(prefix)
        }

        # Headers that are also needed for a browser to handle the played-back
        # memento are *not* prefixed, so we need to copy over each of those.
        # NOTE: Historical 'Content-Encoding' headers cannot be determined from
        # the Wayback Machine; we shouldn't pick up `Content-Encoding` here.
        for unprefixed in ('Content-Type',):
            if unprefixed in raw_headers:
                headers[unprefixed] = raw_headers[unprefixed]

        # The `Location` header for a redirect does not have an X-Archive-Orig-
        # version, and the normal location header point to the next *Wayback*
        # URL, so we need to parse it to get the historical redirect URL.
        if 'Location' not in headers and 'Location' in raw_headers:
            # Some Wayback redirects provide a complete URL with a scheme and
            # host in the `Location` header, not all do. Use `url` as a base
            # URL if the value in the header is missing a scheme, host, etc.
            raw_location = urljoin(url, raw_headers['Location'])
            headers['Location'], _, _ = memento_url_data(raw_location)

        return headers
