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

from datetime import datetime
import hashlib
import re
import requests
from web_monitoring import utils


class WebMonitoringException(Exception):
    # All exceptions raised directly by this package inherit from this.
    ...


class UnexpectedResponseFormat(WebMonitoringException):
    ...


TIMEMAP_URL_TEMPLATE = 'http://web.archive.org/web/timemap/link/{}'
DATE_FMT = '%a, %d %b %Y %H:%M:%S %Z'
DATE_URL_FMT = '%Y%m%d%H%M%S'
URL_CHUNK_PATTERN = re.compile('\<(.*)\>')
DATETIME_CHUNK_PATTERN = re.compile(' datetime="(.*)",')


def list_versions(url):
    """
    Yield (version_datetime, version_uri) for all versions of a url.

    Parameters
    ----------
    url : string

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

    References
    ----------
    * https://ws-dl.blogspot.fr/2013/07/2013-07-15-wayback-machine-upgrades.html
    """
    # Request a list of the 'mementos' (what we call 'versions') for a url.
    # It may be paginated. If so, the final line in the repsonse is a link to
    # the next page.
    first_page_url = TIMEMAP_URL_TEMPLATE.format(url)
    res = requests.get(first_page_url)
    lines = res.iter_lines()

    while True:
        # Continue requesting pages of responses until the last page.
        try:
            # The first three lines contain no information we need.
            for _ in range(3):
                next(lines)
        except StopIteration:
            # There are no more pages left to parse.
            break
        for line in lines:
            # Lines are made up semicolon-separated chunks:
            # b'<http://web.archive.org/web/19961231235847/http://www.nasa.gov:80/>; rel="memento"; datetime="Tue, 31 Dec 1996 23:58:47 GMT",'

            # Split by semicolon. Fail with an informative error if there are
            # not exactly three chunks.
            try:
                url_chunk, rel_chunk, dt_chunk = line.decode().split(';')
            except ValueError:
                raise UnexpectedResponseFormat(line.decode())

            if 'timemap' in rel_chunk:
                # This line is a link to the next page of mementos.
                next_page_url, = URL_CHUNK_PATTERN.match(url_chunk).groups()
                res = requests.get(next_page_url)
                lines = res.iter_lines()
                break

            # Extract the URL and the datetime from the surrounding characters.
            # Again, fail with an informative error.
            try:
                uri, = URL_CHUNK_PATTERN.match(url_chunk).groups()
                dt_str, = DATETIME_CHUNK_PATTERN.match(dt_chunk).groups()
            except AttributeError:
                raise UnexpectedResponseFormat(line.decode())

            dt = datetime.strptime(dt_str, DATE_FMT)
            yield dt, uri


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
    version_hash = hashlib.sha256(res.content).hexdigest()
    title = utils.extract_title(res.content)
    return format_version(url=url, dt=dt, uri=uri,
                          version_hash=version_hash, title=title,
                          agency=agency, site=site)
