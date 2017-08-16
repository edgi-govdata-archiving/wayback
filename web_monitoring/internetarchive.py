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
import urllib
import requests
from web_monitoring import utils


class WebMonitoringException(Exception):
    # All exceptions raised directly by this package inherit from this.
    ...


class UnexpectedResponseFormat(WebMonitoringException):
    ...


CDX_SEARCH_URL = 'http://web.archive.org/cdx/search/cdx'
ARCHIVE_RAW_URL_TEMPLATE = 'http://web.archive.org/web/{timestamp}id_/{url}'
ARCHIVE_VIEW_URL_TEMPLATE = 'http://web.archive.org/web/{timestamp}/{url}'
URL_DATE_FORMAT = '%Y%m%d%H%M%S'

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


def cdx_hash(content):
    if isinstance(content, str):
        content = content.encode()
    return b32encode(hashlib.sha1(content).digest())


def search_cdx(params):
    """
    Search archive.org's CDX API for captures of a given URL. This will
    automatically page through all results for a given search.

    Returns an iterator of CdxRecord objects. The StopIteration value is the
    total count of found captures.

    Note that even URLs without wildcards may return results with different
    URLs. Search results are matched by url_key, which is a SURT-formatted,
    canonicalized URL:
      - Does not differentiate between HTTP and HTTPS
      - Is not case-sensitive
      - Treats `www.` and `www*.` subdomains the same as no subdomain at all

    Parameters
    ----------
    params : dict
           Any options that the CDX API takes. Must at least include `url`.

    References
    ----------
    * https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
    """

    # NOTE: resolveRevisits works on a CDX server version that isn't released.
    # It attempts to automatically resolve `warc/revisit` records.
    params['resolveRevisits'] = 'true'
    params['showResumeKey'] = 'true'

    response = requests.get(CDX_SEARCH_URL, params=params)
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
            encoded_url = urllib.parse.quote(data.url, safe='')
            capture_time = datetime.strptime(data.timestamp, URL_DATE_FORMAT)
        except:
            raise UnexpectedResponseFormat(text)

        # TODO: repeat captures have a status code of `-` and a mime type of
        # `warc/revisit`. These can only be resolved by requesting the content
        # and following redirects. Maybe nice to do so automatically here.
        data = data._replace(
            date=capture_time,
            raw_url=ARCHIVE_RAW_URL_TEMPLATE.format(
                timestamp=data.timestamp, url=encoded_url),
            view_url=ARCHIVE_VIEW_URL_TEMPLATE.format(
                timestamp=data.timestamp, url=encoded_url)
        )
        count += 1
        yield data

    return count


def list_versions(url, *, from_date=None, to_date=None, skip_repeats=True):
    """
    Yield (version_datetime, version_uri) for all versions of a url.

    This function provides a convenient, use-case-specific interface to
    archive.org's CDX API. For a more direct, low-level API, use search_cdx().

    Note that even URLs without wildcards may return results with multiple
    URLs. Search results are matched by url_key, which is a SURT-formatted,
    canonicalized URL:
      - Does not differentiate between HTTP and HTTPS
      - Is not case-sensitive
      - Treats `www.` and `www*.` subdomains the same as no subdomain at all

    Parameters
    ----------
    url : string
        The URL to list versions for. Can contain wildcards.
    from_date : datetime
        Get versions captured after this date (optional).
    to_date : datetime
        Get versions captured before this date (optional).
    skip_repeats : boolean
        Don’t include consecutive captures of unchanged content (default: True).

    Examples
    --------
    Grab the datetime and URL of the version nasa.gov snapshot.
    >>> pairs = list_versions('nasa.gov')
    >>> dt, url = next(pairs)
    >>> dt
    datetime.datetime(1996, 12, 31, 23, 58, 47)
    >>> url
    'http://web.archive.org/web/19961231235847/http://www.nasa.gov:80/'

    Loop through all the snapshots.
    >>> for dt, url in list_versions('nasa.gov'):
    ...     # do something
    """
    params = {'url': url, 'collapse': 'digest'}
    if from_date:
        params['from'] = from_date.strftime(URL_DATE_FORMAT)
    if to_date:
        params['to'] = from_date.strftime(URL_DATE_FORMAT)

    has_versions = False
    last_hashes = {}
    for version in search_cdx(params):
        # TODO: may want to follow redirects and resolve them in the future
        if not skip_repeats or last_hashes.get(version.url) != version.digest:
            has_versions = True
            last_hashes[version.url] = version.digest
            # TODO: yield the whole version
            yield version.date, version.raw_url

    if not has_versions:
        raise ValueError("Internet archive does not have archived "
                         "versions of {}".format(url))


def format_version(*, url, dt, uri, version_hash, title, agency, site):
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
    agency : string
        primer metadata (likely to change in the future)
    site : string
        primer metadata (likely to change in the future)

    Returns
    -------
    version : dict
        properly formatted for as JSON blob for web-monitoring-db
    """
    # Existing documentation of import API is in this PR:
    # https://github.com/edgi-govdata-archiving/web-monitoring-db/pull/32
    return dict(
         page_url=url,
         page_title=title,
         site_agency=agency,
         site_name=site,
         capture_time=dt.isoformat(),
         uri=uri,
         version_hash=version_hash,
         source_type='internet_archive',
         source_metadata={}  # TODO Use CDX API to get additional metadata.
    )


def timestamped_uri_to_version(dt, uri, *, url, site, agency):
    """
    Obtain hash and title and return a Version.
    """
    res = requests.get(uri)
    assert res.ok
    version_hash = utils.hash_content(res.content)
    title = utils.extract_title(res.content)
    # TODO: extract more metadata from X-Archive-Orig-* headers
    return format_version(url=url, dt=dt, uri=uri,
                          version_hash=version_hash, title=title,
                          agency=agency, site=site)
