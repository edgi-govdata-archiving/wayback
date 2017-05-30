# PageFreezer API for EDGI
# v 1.1

# Provides low-level, stateless Python functions wrapping the REST API.
# Fails loudly (with exceptions) if REST API reports bad status.

import requests


BASE = 'https://edgi.pagefreezer.com/'


def list_cabinets():
    url = f'{BASE}/master/api/services/storage/library/all/cabinets'
    res = requests.get(url)
    assert res.ok  # server is OK
    content = res.json()
    assert content['status'] == 'ok'  # business logic is OK
    return content['cabinets']


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
