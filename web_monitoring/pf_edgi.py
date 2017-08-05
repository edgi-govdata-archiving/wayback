# PageFreezer API for EDGI
# v 1.1

# Provides low-level, stateless Python functions wrapping the REST API.
# Fails loudly (with exceptions) if REST API reports bad status.
from datetime import datetime
import requests
from web_monitoring import utils
from urllib.parse import urlparse

BASE = 'https://edgi.pagefreezer.com/'

def list_cabinets():
    url = f'{BASE}/master/api/services/storage/library/all/cabinets'
    res = requests.get(url)
    assert res.ok  # server is OK
    content = res.json()
    assert content['status'] == 'ok'  # business logic is OK
    return content['cabinets']

def get_cabinet_id(url):
    cabinets = list_cabinets()
    cabinet_id = ''

    if(url.find('://') == -1):
        try_urls = ['https://' + url,'http://' + url]
    elif(url.find('://') == 4):
        try_urls = [url , 'https' + url[4:]]
    else:
        try_urls = [url, 'http' + url[5:]]

    for key,value in cabinets.items():
        for dictionary in value:
            if(str(urlparse(dictionary['url']).scheme + '://' + urlparse(dictionary['url']).netloc) in try_urls):
                cabinet_id = dictionary['name']

    if not cabinet_id != '' : raise ValueError("No such url found in the cabinets.")

    return cabinet_id


def list_archives(cabinet_id):
    url = f'{BASE}/master/api/services/storage/archive/{cabinet_id}'
    res = requests.get(url)
    assert res.ok  # server is OK
    content = res.json()
    assert content['status'] == 'ok'  # business logic is OK
    assert content['cabinet'] == cabinet_id
    return content['archives']


def _command_archive(method, cabinet_id, archive_id, command, **kwargs):
    # called by load_archive, unload_archive, search_archive
    url = (f'{BASE}/master/api/services/storage/archive/{cabinet_id}/'
           f'{archive_id}/{command}')
    res = getattr(requests, method)(url, params=kwargs)
    assert res.ok  # server is OK
    content = res.json()
    assert content['status'] == 'ok'  # business logic is OK
    return content


def load_archive(cabinet_id, archive_id):
    content = _command_archive('put', cabinet_id, archive_id, 'load')
    assert content['result']['status'] == 'ok'
    return content['result']


def unload_archive(cabinet_id, archive_id):
    content = _command_archive('delete', cabinet_id, archive_id, 'unload')
    assert content['result']['status'] == 'ok'
    return content['result']


def search_archive(cabinet_id, archive_id, query):
    content = _command_archive('get', cabinet_id, archive_id, 'search',
                               query=query)
    return content['result']


def file_command_uri(cabinet_id, archive_id, page_key, command):
    # called by get_file_metadata, get_file
    return (f'{BASE}/master/api/services/storage/archive/{cabinet_id}/'
            f'{archive_id}/{page_key}/{command}')


def get_file_metadata(cabinet_id, archive_id, page_key):
    uri = file_command_uri(cabinet_id, archive_id, page_key, 'meta')
    res = requests.get(uri)
    assert res.ok  # server is OK
    content = res.json()
    assert content['status'] == 'ok'  # business logic is OK
    assert content['result']['status'] == 'ok'
    return content['result']


def get_file(cabinet_id, archive_id, page_key):
    uri = file_command_uri(cabinet_id, archive_id, page_key, 'file')
    res = requests.get(uri)
    assert res.ok  # server is OK
    return res.content  # intentionally un-decoded bytes


def format_version(*, url, dt, uri, version_hash, title, agency, site,
                   metadata):
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
         source_type='page_freezer',
         source_metadata=metadata
    )


def page_to_version(url, cabinet_id, archive_id, page_key, *,
                    agency, site):
    """
    Obtain URI, timestamp, metadata, hash, and title and return a Version.
    """
    uri = file_command_uri(cabinet_id, archive_id, page_key, 'file')
    dt = datetime.fromtimestamp(int(archive_id))
    metadata = get_file_metadata(cabinet_id, archive_id, page_key)
    content = get_file(cabinet_id, archive_id, page_key)
    version_hash = utils.hash_content(content)

    # Sniff whether this is text and, if so, what the encoding is.
    # PF provides its own 'ContentType' key, mapped to a string,
    # not to be confused with 'Content-Type' in the Header, mapped to a list.
    content_type = metadata['file']['ContentType']
    is_text = content_type.startswith('text/html')
    if is_text:
        if 'charset=' in content_type:
            _, encoding = content_type.split('charset=')
        else:
            encoding = 'utf-8'  # best effort
        title = utils.extract_title(content, encoding)
    else:
        title = ''
    version = format_version(url=url, dt=dt, uri=uri,
                             version_hash=version_hash, title=title,
                             agency=agency, site=site,
                             metadata=metadata)
    return version


def archive_to_versions(cabinet_id, archive_id, *, agency, site):
    """
    Yield formatted Versions for every page in a PF archive.
    """
    load_archive(cabinet_id, archive_id)
    results = search_archive(cabinet_id, archive_id, '')['founds']
    for result in results:
        yield page_to_version(result['url'], cabinet_id, archive_id,
                              result['key'], agency=agency, site=site)
    unload_archive(cabinet_id, archive_id)


def unique_subdomains(cabinets):
    """
    A convenience function for producing a flat list of cabinet subdomains.
    """
    return set([entry['url']
                for cabinet in cabinets.values()
                for entry in cabinet])
