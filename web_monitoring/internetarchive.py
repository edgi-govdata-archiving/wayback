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
import re
import requests



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

def check_exists(lines):    
    """
    Check if Internet Archive has archived versions of a url.
    """


    try:
        # The first three lines contain no information we need.
        for _ in range(3):
            next(lines)
            

    except StopIteration:
        print("Internet archive does not have archived versions of this url.")
        return False

    return True


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

    exists = check_exists(lines)
    if exists:

        while True:

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
    else:
        yield None,None
