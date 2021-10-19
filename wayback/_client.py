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
import requests
from requests.exceptions import (ChunkedEncodingError,
                                 ConnectionError,
                                 ContentDecodingError,
                                 ProxyError,
                                 RetryError,
                                 Timeout)
import time
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import (ConnectTimeoutError,
                                MaxRetryError,
                                ReadTimeoutError)
from . import _utils, __version__
from ._models import CdxRecord, Memento
from .exceptions import (WaybackException,
                         UnexpectedResponseFormat,
                         BlockedByRobotsError,
                         BlockedSiteError,
                         MementoPlaybackError,
                         NoMementoError,
                         WaybackRetryError,
                         RateLimitError)


logger = logging.getLogger(__name__)

CDX_SEARCH_URL = 'http://web.archive.org/cdx/search/cdx'
# This /web/timemap URL has newer features, but has other bugs and doesn't
# support some features, like resume keys (for paging). It ignores robots.txt,
# while /cdx/search obeys robots.txt (for now). It also has different/extra
# columns. See
# https://github.com/internetarchive/wayback/blob/bd205b9b26664a6e2ea3c0c2a8948f0dc6ff4519/wayback-cdx-server/src/main/java/org/archive/cdxserver/format/CDX11Format.java#L13-L17  # noqa
# NOTE: the `length` and `robotflags` fields appear to always be empty
# TODO: support new/upcoming CDX API
# CDX_SEARCH_URL = 'http://web.archive.org/web/timemap/cdx'

ARCHIVE_URL_TEMPLATE = 'http://web.archive.org/web/{timestamp}{mode}/{url}'
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


class Mode(Enum):
    """
    An enum describing the playback mode of a memento. When requesting a
    memento (e.g. with :meth:`wayback.WaybackClient.get_memento`), you can use
    these values to determine how the response body should be formatted.

    For more details, see:
    http://archive-access.sourceforge.net/projects/wayback/administrator_manual.html#Archival_URL_Replay_Mode

    Examples
    --------
    >>> waybackClient.get_memento('https://noaa.gov/',
    >>>                           datetime=datetime.datetime(2018, 1, 2),
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


def cdx_hash(content):
    if isinstance(content, str):
        content = content.encode()
    return b32encode(hashlib.sha1(content).digest()).decode()


def read_and_close(response):
    # Read content so it gets cached and close the response so
    # we can release the connection for reuse. See:
    # https://github.com/psf/requests/blob/eedd67462819f8dbf8c1c32e77f9070606605231/requests/sessions.py#L160-L163
    try:
        response.content
    except (ChunkedEncodingError, ContentDecodingError, RuntimeError):
        response.raw.read(decode_content=False)
    finally:
        response.close()


#####################################################################
# HACK: handle malformed Content-Encoding headers from Wayback.
# When you send `Accept-Encoding: gzip` on a request for a memento, Wayback
# will faithfully gzip the response body. However, if the original response
# from the web server that was snapshotted was gzipped, Wayback screws up the
# `Content-Encoding` header on the memento response, leading any HTTP client to
# *not* decompress the gzipped body. Wayback folks have no clear timeline for
# a fix, hence the workaround here. More info in this issue:
# https://github.com/edgi-govdata-archiving/web-monitoring-processing/issues/309
#
# This subclass of urllib3's response class identifies the malformed headers
# and repairs them before instantiating the actual response object, so when it
# reads the body, it knows to decode it correctly.
#
# See what we're overriding from urllib3:
# https://github.com/urllib3/urllib3/blob/a6ec68a5c5c5743c59fe5c62c635c929586c429b/src/urllib3/response.py#L499-L526
class WaybackResponse(HTTPConnectionPool.ResponseCls):
    @classmethod
    def from_httplib(cls, httplib_response, **response_kwargs):
        headers = httplib_response.msg
        pairs = headers.items()
        if ('content-encoding', '') in pairs and ('Content-Encoding', 'gzip') in pairs:
            del headers['content-encoding']
            headers['Content-Encoding'] = 'gzip'
        return super().from_httplib(httplib_response, **response_kwargs)


HTTPConnectionPool.ResponseCls = WaybackResponse
# END HACK
#####################################################################


# TODO: make rate limiting configurable at the session level, rather than
# arbitrarily set inside get_memento(). Idea: have a rate limit lock type and
# pass an instance to the constructor here.
class WaybackSession(_utils.DisableAfterCloseSession, requests.Session):
    """
    A custom session object that network pools connections and resources for
    requests to the Wayback Machine.

    Parameters
    ----------
    retries : int, optional
        The maximum number of retries for requests.
    backoff : int or float, optional
        Number of seconds from which to calculate how long to back off and wait
        when retrying requests. The first retry is always immediate, but
        subsequent retries increase by powers of 2:

            seconds = backoff * 2 ^ (retry number - 1)

        So if this was `4`, retries would happen after the following delays:
        0 seconds, 4 seconds, 8 seconds, 16 seconds, ...
    timeout : int or float or tuple of (int or float, int or float), optional
        A timeout to use for all requests. (Default: ``60``)
        See the Requests docs for more:
        http://docs.python-requests.org/en/master/user/advanced/#timeouts
    user_agent : str, optional
        A custom user-agent string to use in all requests. Defaults to:
        `wayback/{version} (+https://github.com/edgi-govdata-archiving/wayback)`
    """

    # It seems Wayback sometimes produces 500 errors for transient issues, so
    # they make sense to retry here. Usually not in other contexts, though.
    retryable_statuses = frozenset((413, 421, 429, 500, 502, 503, 504, 599))

    retryable_errors = (ConnectTimeoutError, MaxRetryError, ReadTimeoutError,
                        ProxyError, RetryError, Timeout)
    # Handleable errors *may* be retryable, but need additional logic beyond
    # just the error type. See `should_retry_error()`.
    handleable_errors = (ConnectionError,) + retryable_errors

    def __init__(self, retries=6, backoff=2, timeout=60, user_agent=None):
        super().__init__()
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.headers = {
            'User-Agent': (user_agent or
                           f'wayback/{__version__} (+https://github.com/edgi-govdata-archiving/wayback)'),
            'Accept-Encoding': 'gzip, deflate'
        }
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

    # Customize the built-in `send` functionality with retryability.
    # NOTE: worth considering whether we should push this logic to a custom
    # requests.adapters.HTTPAdapter
    def send(self, *args, **kwargs):
        total_time = 0
        maximum = self.retries
        retries = 0
        while True:
            try:
                result = super().send(*args, **kwargs)
                if retries >= maximum or not self.should_retry(result):
                    if result.status_code == 429:
                        raise RateLimitError(result)
                    return result
            except WaybackSession.handleable_errors as error:
                response = getattr(error, 'response', None)
                if response:
                    read_and_close(response)

                if retries >= maximum:
                    raise WaybackRetryError(retries, total_time, error) from error
                elif not self.should_retry_error(error):
                    raise

            # The first retry has no delay.
            if retries > 0:
                seconds = self.backoff * 2 ** (retries - 1)
                total_time += seconds
                time.sleep(seconds)

            retries += 1

    # Customize `request` in order to set a default timeout from the session.
    # We can't do this in `send` because `request` always passes a `timeout`
    # keyword to `send`. Inside `send`, we can't tell the difference between a
    # user explicitly requesting no timeout and not setting one at all.
    def request(self, method, url, **kwargs):
        """
        Perform an HTTP request using this session. For arguments and return
        values, see:
        https://requests.readthedocs.io/en/latest/api/#requests.Session.request

        If the ``timeout`` keyword argument is not set, it will default to the
        session's ``timeout`` attribute.
        """
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout
        return super().request(method, url, **kwargs)

    def should_retry(self, response):
        # A memento may actually be a capture of an error, so don't retry it :P
        if 'Memento-Datetime' in response.headers:
            return False

        return response.status_code in self.retryable_statuses

    def should_retry_error(self, error):
        if isinstance(error, WaybackSession.retryable_errors):
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

    def reset(self):
        "Reset any network connections the session is using."
        # Close really just closes all the adapters in `self.adapters`. We
        # could do that directly, but `self.adapters` is not documented/public,
        # so might be somewhat risky.
        self.close(disable=False)
        # Re-build the standard adapters. See:
        # https://github.com/kennethreitz/requests/blob/v2.22.0/requests/sessions.py#L415-L418
        self.mount('https://', requests.adapters.HTTPAdapter())
        self.mount('http://', requests.adapters.HTTPAdapter())


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
    session : :class:`requests.Session`, optional
    """
    def __init__(self, session=None):
        self.session = session or WaybackSession()

    def __exit_all__(self, type, value, traceback):
        self.close()

    def close(self):
        "Close the client's session."
        self.session.close()

    def search(self, url, *, matchType=None, limit=None, offset=None,
               fastLatest=None, gzip=None, from_date=None, to_date=None,
               filter_field=None, collapse=None, showResumeKey=True,
               resumeKey=None, page=None, pageSize=None, resolveRevisits=True,
               skip_malformed_results=True, previous_result=None, **kwargs):
        """
        Search archive.org's CDX API for all captures of a given URL.

        This will automatically page through all results for a given search.

        Returns an iterator of CdxRecord objects. The StopIteration value is
        the total count of found captures.

        Note that even URLs without wildcards may return results with different
        URLs. Search results are matched by url_key, which is a SURT-formatted,
        canonicalized URL:

        * Does not differentiate between HTTP and HTTPS
        * Is not case-sensitive
        * Treats ``www.`` and ``www*.`` subdomains the same as no subdomain at
          all

        Note not all CDX API parameters are supported. In particular, this does
        not support: `output`, `fl`, `showDupeCount`, `showSkipCount`,
        `lastSkipTimestamp`, `showNumPages`, `showPagedIndex`.

        Parameters
        ----------
        url : str
            The URL to query for captures of.
        matchType : str, optional
            Must be one of 'exact', 'prefix', 'host', or 'domain'. The default
            value is calculated based on the format of `url`.
        limit : int, optional
            Maximum number of results per page (this iterator will continue to
            move through all pages unless `showResumeKey=False`, though).
        offset : int, optional
            Skip the first N results.
        fastLatest : bool, optional
            Get faster results when using a negative value for `limit`. It may
            return a variable number of results.
        gzip : bool, optional
            Whether output should be gzipped.
        from_date : datetime or date, optional
            Only include captures after this date. Equivalent to the
            `from` argument in the CDX API. If it does not have a time zone, it
            is assumed to be in UTC.
        to_date : datetime or date, optional
            Only include captures before this date. Equivalent to the `to`
            argument in the CDX API. If it does not have a time zone, it is
            assumed to be in UTC.
        filter_field : str, optional
            A filter for any field in the results. Equivalent to the `filter`
            argument in the CDX API. (format: `[!]field:regex`)
        collapse : str, optional
            Collapse consecutive results that match on a given field. (format:
            `fieldname` or `fieldname:N` -- N is the number of chars to match.)
        showResumeKey : bool, optional
            If False, don't continue to iterate through all pages of results.
            The default value is True
        resumeKey : str, optional
            Start returning results from a specified resumption point/offset.
            The value for this is supplied by the previous page of results when
            `showResumeKey` is True.
        page : int, optional
            If using paging start from this page number (note: paging, as
            opposed to the using `resumeKey` is somewhat complicated because
            of the interplay with indexes and index sizes).
        pageSize : int, optional
            The number of index blocks to examine for each page of results.
            Index blocks generally cover about 3,000 items, so setting
            `pageSize=1` might return anywhere from 0 to 3,000 results per page.
        resolveRevists : bool, optional
            Attempt to resolve `warc/revisit` records to their actual content
            type and response code. Not supported on all CDX servers. Defaults
            to True.
        skip_malformed_results : bool, optional
            If true, don't yield records that look like they have no actual
            memento associated with them. Some crawlers will erroneously
            attempt to capture bad URLs like `http://mailto:someone@domain.com`
            or `http://data:image/jpeg;base64,AF34...` and so on. This is a
            filter performed client side and is not a CDX API argument.
            (Default: True)
        previous_result : str, optional
            *For internal use.* The CDX API sometimes returns repeated results.
            This is used to track the previous result so we can filter out the
            repeats.
        **kwargs
            Any additional CDX API options.

        Raises
        ------
        UnexpectedResponseFormat
            If the CDX response was not parseable.

        References
        ----------
        * https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server

        Yields
        ------
        version: CdxRecord
            A :class:`CdxRecord` encapsulating one capture or revisit
        """

        # TODO: support args that can be set multiple times: filter, collapse
        # Should take input as a sequence and convert to repeat query args
        # TODO: support args that add new fields to the results or change the
        # result format
        query = {'url': url, 'matchType': matchType, 'limit': limit,
                 'offset': offset, 'gzip': gzip, 'from': from_date,
                 'to': to_date, 'filter': filter_field,
                 'fastLatest': fastLatest, 'collapse': collapse,
                 'showResumeKey': showResumeKey, 'resumeKey': resumeKey,
                 'resolveRevisits': resolveRevisits, 'page': page,
                 'pageSize': page}
        query.update(kwargs)

        unsupported = {'output', 'fl', 'showDupeCount', 'showSkipCount',
                       'lastSkipTimestamp', 'showNumPages', 'showPagedIndex'}

        final_query = {}
        for key, value in query.items():
            if key in unsupported:
                raise ValueError(f'The {key} argument is not supported')

            if value is not None:
                if isinstance(value, str):
                    final_query[key] = value
                elif isinstance(value, date):
                    final_query[key] = _utils.format_timestamp(value)
                else:
                    final_query[key] = str(value).lower()

        response = self.session.request('GET', CDX_SEARCH_URL,
                                        params=final_query)
        try:
            # Read/cache the response and close straightaway. If we need to
            # raise for status, we want to pre-emptively close the response
            # so a user handling the error doesn't need to worry about it. If
            # we don't raise here, we still want to close the connection so it
            # doesn't leak when we move onto the next of results or when this
            # iterator ends.
            read_and_close(response)
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            if 'AdministrativeAccessControlException' in response.text:
                raise BlockedSiteError(query['url'])
            elif 'RobotAccessControlException' in response.text:
                raise BlockedByRobotsError(query['url'])
            else:
                raise WaybackException(str(error))

        lines = iter(response.content.splitlines())
        count = 0

        for line in lines:
            text = line.decode()

            # The resume key is delineated by a blank line.
            if text == '':
                next_args = query.copy()
                next_args['resumeKey'] = next(lines).decode()
                count += yield from self.search(previous_result=previous_result,
                                                **next_args)
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
                    f'Could not parse CDX output: "{text}" (query: {final_query})') from err

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
                raw_url=ARCHIVE_URL_TEMPLATE.format(
                    url=data.url,
                    timestamp=data.timestamp,
                    mode=Mode.original.value),
                view_url=ARCHIVE_URL_TEMPLATE.format(
                    url=data.url,
                    timestamp=data.timestamp,
                    mode=Mode.view.value)
            )
            count += 1
            yield data

        return count

    def get_memento(self, url, datetime=None, mode=Mode.original, *,
                    exact=True, exact_redirects=None,
                    target_window=24 * 60 * 60, follow_redirects=True):
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
              form, you must also specify ``datetime``.
            - A ``CdxRecord`` retrieved from
              :meth:`wayback.WaybackClient.search`.
            - A URL of the memento in Wayback, e.g.
              ``http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/``

        datetime : datetime.datetime or datetime.date or str, optional
            The time at which to retrieve a memento of ``url``. If ``url`` is
            a :class:`wayback.CdxRecord` or full memento URL, this parameter
            can be omitted.
        mode : wayback.Mode or str, optional
            The playback mode of the memento. This determines whether the
            content of the returned memento is exactly as originally captured
            (the default) or modified in some way. See :class:`wayback.Mode`
            for a description of possible values.

            For more details, see:
            http://archive-access.sourceforge.net/projects/wayback/administrator_manual.html#Archival_URL_Replay_Mode

            Default: :py:attr:`wayback.Mode.original`

        exact : boolean, optional
            If false and the requested memento either doesn't exist or can't be
            played back, this returns the closest-in-time memento to the
            requested one, so long as it is within ``target_window``. If there
            was no memento in the target window or if ``exact=True``, then this
            will raise :class:`wayback.exceptions.MementoPlaybackError`.
            Default: True
        exact_redirects : boolean, optional
            If false and the requested memento is a redirect whose *target*
            doesn't exist or can't be played back, this returns the
            closest-in-time memento to the intended target, so long as it is
            within ``target_window``. If unset, this will be the same as
            ``exact``.
        target_window : int, optional
            If the memento is of a redirect, allow up to this many seconds
            between the capture of the redirect and the capture of the
            redirect's target URL. This window also applies to the first
            memento if ``exact=False`` and the originally
            requested memento was not available.
            Defaults to 86,400 (24 hours).
        follow_redirects : boolean, optional
            If true (the default), ``get_memento`` will follow historical
            redirects to return the content that a web browser would have
            ultimately displayed at the requested URL and time, rather than the
            memento of an HTTP redirect response (i.e. a 3xx status code).
            That is, if ``http://example.com/a`` redirected to
            ``http://example.com/b``, then this method returns the memento for
            ``/a`` when ``follow_redirects=False`` and the memento for ``/b``
            when ``follow_redirects=True``.
            Default: True

        Returns
        -------
        dict : requests.Response
            An HTTP response with the content of the memento, including a
            history of any redirects involved. (For a complete history of all
            HTTP requests needed to obtain the memento [rather than historic
            redirects], check ``debug_history`` instead of ``history``.)
        """
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
                if not datetime:
                    raise TypeError('You must specify `datetime` when using a '
                                    'normal URL for get_memento()')
                else:
                    original_date = _utils.ensure_utc_datetime(datetime)

        original_date_wayback = _utils.format_timestamp(original_date)
        url = ARCHIVE_URL_TEMPLATE.format(timestamp=original_date_wayback,
                                          mode=mode,
                                          url=original_url)

        with _utils.rate_limited(calls_per_second=30, group='get_memento'):
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
                is_memento = 'Memento-Datetime' in response.headers
                current_url, current_date, current_mode = _utils.memento_url_data(response.url)

                if is_memento:
                    memento = Memento(url=current_url,
                                      timestamp=current_date,
                                      mode=current_mode,
                                      memento_url=response.url,
                                      status_code=response.status_code,
                                      headers=Memento.parse_memento_headers(response.headers, response.url),
                                      encoding=response.encoding,
                                      raw=response,
                                      raw_headers=response.headers,
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
                    if response.next and (
                       (len(history) == 0 and not exact) or
                       (len(history) > 0 and (previous_was_memento or not exact_redirects))):
                        target_url, target_date, _ = _utils.memento_url_data(response.next.url)
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
                        read_and_close(response)
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
                        elif response.ok:
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

                if response.next:
                    previous_was_memento = is_memento
                    read_and_close(response)

                    # Wayback sometimes has circular memento redirects ¯\_(ツ)_/¯
                    urls.add(response.url)
                    if response.next.url in urls:
                        raise MementoPlaybackError(f'Memento at {url} is circular')

                    # All requests are included in `debug_history`, but
                    # `history` only shows redirects that were mementos.
                    debug_history.append(response.url)
                    if is_memento:
                        history.append(memento)
                    response = self.session.send(response.next, allow_redirects=False)
                else:
                    break

            return memento
