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
from collections import namedtuple
from datetime import datetime
import hashlib
import urllib.parse
import re
import requests
from web_monitoring import utils


class WebMonitoringException(Exception):
    # All exceptions raised directly by this package inherit from this.
    ...


class UnexpectedResponseFormat(WebMonitoringException):
    ...


class MementoPlaybackError(WebMonitoringException):
    ...


CDX_SEARCH_URL = 'http://web.archive.org/cdx/search/cdx'
ARCHIVE_RAW_URL_TEMPLATE = 'http://web.archive.org/web/{timestamp}id_/{url}'
ARCHIVE_VIEW_URL_TEMPLATE = 'http://web.archive.org/web/{timestamp}/{url}'
URL_DATE_FORMAT = '%Y%m%d%H%M%S'
MEMENTO_URL_PATTERN = re.compile(
    r'^http(?:s)?://web.archive.org/web/\d+(?:id_)?/(.*)$')
REDUNDANT_HTTP_PORT = re.compile(r'^(http://[^:/]+):80(.*)$')
REDUNDANT_HTTPS_PORT = re.compile(r'^(https://[^:/]+):443(.*)$')

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
    'date',
    'raw_url',
    'view_url'
))


def original_url_for_memento(memento_url):
    """
    Get the original URL that a memento URL represents a capture of.

    Examples
    --------
    Extract original URL.
    >>> original_url_for_memento('http://web.archive.org/web/20170813195036/https://arpa-e.energy.gov/?q=engage/events-workshops')
    'https://arpa-e.energy.gov/?q=engage/events-workshops'
    """
    try:
        url = MEMENTO_URL_PATTERN.match(memento_url).group(1)
    except:
        raise ValueError(f'"{memento_url}" is not a memento URL')

    # A URL *may* be percent encoded, decode ONLY if so (we don’t want to
    # accidentally decode the querystring if there is one)
    lower_url = url.lower()
    if lower_url.startswith('http%3a') or lower_url.startswith('https%3a'):
        url = urllib.parse.unquote(url)

    return url


def cdx_hash(content):
    if isinstance(content, str):
        content = content.encode()
    return b32encode(hashlib.sha1(content).digest()).decode()


def search_cdx(params):
    """
    Search archive.org's CDX API for all captures of a given URL.

    This will automatically page through all results for a given search.

    Returns an iterator of CdxRecord objects. The StopIteration value is the
    total count of found captures.

    Note that even URLs without wildcards may return results with different
    URLs. Search results are matched by url_key, which is a SURT-formatted,
    canonicalized URL:

      * Does not differentiate between HTTP and HTTPS
      * Is not case-sensitive
      * Treats `www.` and `www*.` subdomains the same as no subdomain at all

    Parameters
    ----------
    params : dict
           Any options that the CDX API takes. Must at least include `url`.

    Raises
    ------
    UnexpectedResponseFormat
        If the CDX response was not parseable.

    References
    ----------
    * https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
    """

    # NOTE: resolveRevisits works on a CDX server version that isn't released.
    # It attempts to automatically resolve `warc/revisit` records.
    params['resolveRevisits'] = 'true'
    params['showResumeKey'] = 'true'

    response = utils.retryable_request('GET', CDX_SEARCH_URL, params=params)
    lines = response.iter_lines()
    count = 0

    for line in lines:
        text = line.decode()

        # The resume key is delineated by a blank line.
        if text == '':
            params['resumeKey'] = next(lines).decode()
            count += yield from search_cdx(params)
            break

        try:
            data = CdxRecord(*text.split(' '), None, '', '')
            capture_time = datetime.strptime(data.timestamp, URL_DATE_FORMAT)
        except Exception:
            raise UnexpectedResponseFormat(text)

        clean_url = REDUNDANT_HTTPS_PORT.sub(
            r'\1\2', REDUNDANT_HTTP_PORT.sub(
                r'\1\2', data.url))
        if clean_url != data.url:
            data = data._replace(url=clean_url)

        # TODO: repeat captures have a status code of `-` and a mime type of
        # `warc/revisit`. These can only be resolved by requesting the content
        # and following redirects. Maybe nice to do so automatically here.
        data = data._replace(
            date=capture_time,
            raw_url=ARCHIVE_RAW_URL_TEMPLATE.format(
                timestamp=data.timestamp, url=data.url),
            view_url=ARCHIVE_VIEW_URL_TEMPLATE.format(
                timestamp=data.timestamp, url=data.url)
        )
        count += 1
        yield data

    return count


def list_versions(url, *, from_date=None, to_date=None, skip_repeats=True,
                  cdx_params=None):
    """
    Search archive.org for captures of a URL (optionally, within a time span).

    This function provides a convenient, use-case-specific interface to
    archive.org's CDX API. For a more direct, low-level API, use
    :func:`search_cdx`.

    Note that even URLs without wildcards may return results with multiple
    URLs. Search results are matched by url_key, which is a SURT-formatted,
    canonicalized URL:

      * Does not differentiate between HTTP and HTTPS
      * Is not case-sensitive
      * Treats `www.` and `www*.` subdomains the same as no subdomain at all

    Parameters
    ----------
    url : string
        The URL to list versions for. Can contain wildcards.
    from_date : datetime, optional
        Get versions captured after this date.
    to_date : datetime, optional
        Get versions captured before this date.
    skip_repeats : boolean, optional
        Don’t include consecutive captures of the same content (default: True).
    cdx_params : dict, optional
        Additional options to pass directly to the CDX API when querying.

    Raises
    ------
    UnexpectedResponseFormat
        If the CDX response was not parseable.
    ValueError
        If there were no versions of the given URL.

    Examples
    --------
    Grab the datetime and URL of the version nasa.gov snapshot.
    >>> versions = list_versions('nasa.gov')
    >>> version = next(versions)
    >>> version.date
    datetime.datetime(1996, 12, 31, 23, 58, 47)
    >>> version.raw_url
    "http://web.archive.org/web/19961231235847id\_/http://www.nasa.gov:80/"

    Loop through all the snapshots.
    >>> for version in list_versions('nasa.gov'):
    ...     # do something
    """
    params = {'collapse': 'digest'}
    if cdx_params:
        params.update(cdx_params)
    params['url'] = url
    if from_date:
        params['from'] = from_date.strftime(URL_DATE_FORMAT)
    if to_date:
        params['to'] = to_date.strftime(URL_DATE_FORMAT)

    last_hashes = {}
    for version in search_cdx(params):
        # TODO: may want to follow redirects and resolve them in the future
        if not skip_repeats or last_hashes.get(version.url) != version.digest:
            last_hashes[version.url] = version.digest
            # TODO: yield the whole version
            yield version

    if not last_hashes:
        raise ValueError("Internet archive does not have archived "
                         "versions of {}".format(url))


def format_version(*, url, dt, uri, version_hash, title, status, mime_type,
                   encoding, maintainers=None, tags=None, headers=None,
                   view_url=None, redirected_url=None, redirects=None):
    """
    Format version info in preparation for submitting it to web-monitoring-db.

    Parameters
    ----------
    url : string
        page URL
    dt : datetime.datetime
        capture time
    uri : string
        URI of version
    version_hash : string
        sha256 hash of version content
    title : string
        primer metadata (likely to change in the future)
    status : int
        HTTP status code
    mime_type : string
        Mime type of HTTP response
    encoding : string
        Character encoding of HTTP response
    maintainers : list of string, optional
        Entities responsible for maintaining the page, as a list of strings
    tags : list of string, optional
        Any arbitrary "tags" to apply to the page for categorization
    headers : dict, optional
        Any relevant HTTP headers from response
    view_url : string, optional
        The archive.org URL for viewing the page (with rewritten links, etc.)
    redirected_url : string, optional
        If getting `url` resulted in a redirect, this should be the URL
        that was ultimately redirected to.
    redirects : sequence, optional
        If getting `url` resulted in any redirects this should be a sequence
        of all the URLs that were retrieved, starting with the originally
        requested URL and ending with the value of the `redirected_url` arg.

    Returns
    -------
    version : dict
        properly formatted for as JSON blob for web-monitoring-db
    """
    # The reason that this is a function, not just dict(**kwargs), is that we
    # have to scope information that is not part of web-monitoring-db's Version
    # format into source_metadata, a free-form object for extra info that not
    # all sources are required to provide.
    metadata = {
        'status_code': status,
        'mime_type': mime_type,
        'encoding': encoding,
        'headers': headers or {},
        'view_url': view_url
    }

    if status >= 400:
        metadata['error_code'] = status

    if redirected_url:
        metadata['redirected_url'] = redirected_url
        metadata['redirects'] = redirects

    return dict(
         page_url=url,
         page_maintainers=maintainers,
         page_tags=tags,
         title=title,
         capture_time=dt.isoformat(),
         uri=uri,
         version_hash=version_hash,
         source_type='internet_archive',
         source_metadata=metadata
    )


def timestamped_uri_to_version(dt, uri, *, url, maintainers=None, tags=None,
                               view_url=None):
    """
    Fetch version content and combine it with metadata to build a Version.

    Parameters
    ----------
    dt : datetime.datetime
        capture time
    uri : string
        URI of version
    url : string
        page URL
    maintainers : list of string, optional
        Entities responsible for maintaining the page, as a list of strings
    tags : list of string, optional
        Any arbitrary "tags" to apply to the page for categorization
    view_url : string, optional
        The archive.org URL for viewing the page (with rewritten links, etc.)

    Returns
    -------
    dict : Version
        suitable for passing to :class:`Client.add_versions`
    """
    with utils.rate_limited(group='timestamped_uri_to_version'):
        # Check to make sure we are actually getting a memento playback.
        res = utils.retryable_request('GET', uri, allow_redirects=False)
        if res.headers.get('memento-datetime') is None:
            if not res.ok:
                res.raise_for_status()
            else:
                raise MementoPlaybackError(f'Memento at {uri} was not playback-able')

        # If the playback includes a redirect, continue on.
        if res.status_code >= 300 and res.status_code < 400:
            original = res
            res = utils.retryable_request('GET', res.headers.get('location'))
            res.history.insert(0, original)
            res.request = original.request

    version_hash = utils.hash_content(res.content)
    title = utils.extract_title(res.content)
    content_type = (res.headers['content-type'] or '').split(';', 1)

    # Get all headers from original response
    prefix = 'X-Archive-Orig-'
    original_headers = {
        k[len(prefix):]: v for k, v in res.headers.items()
        if k.startswith(prefix)
    }

    redirected_url = None
    redirects = None
    if res.url != uri:
        redirected_url = original_url_for_memento(res.url)
        redirects = list(map(
            lambda response: original_url_for_memento(response.url),
            res.history))
        redirects.append(redirected_url)

    return format_version(url=url, dt=dt, uri=uri,
                          version_hash=version_hash, title=title, tags=tags,
                          maintainers=maintainers, status=res.status_code,
                          mime_type=content_type[0], encoding=res.encoding,
                          headers=original_headers, view_url=view_url,
                          redirected_url=redirected_url, redirects=redirects)
