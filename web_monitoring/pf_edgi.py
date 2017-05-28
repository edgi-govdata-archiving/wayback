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


def _command_file(cabinet_id, archive_id, page_key, command):
    # called by get_file_metadata, get_file
    url = (f'{BASE}/master/api/services/storage/archive/{cabinet_id}/'
           f'{archive_id}/{page_key}/{command}')
    res = requests.get(url)
    assert res.ok  # server is OK
    # Return raw Response because 'metadata' is JSON but 'file' is not.
    return res


def get_file_metadata(cabinet_id, archive_id, page_key):
    res = _command_file(cabinet_id, archive_id, page_key, 'meta')
    content = res.json()
    assert content['status'] == 'ok'  # business logic is OK
    assert content['result']['status'] == 'ok'
    return content['result']


def get_file(cabinet_id, archive_id, page_key):
    res = _command_file(cabinet_id, archive_id, page_key, 'file')
    return res.content  # intentionally un-decoded bytes
