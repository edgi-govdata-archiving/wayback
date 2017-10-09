# This module expects a local deployment of web-monitoring-db to be running
# with the default settings.

# The purpose is to test that the Python API can exercise all parts of the REST
# API. It is not meant to thoroughly check the correctness of the REST API.
from datetime import datetime, timedelta
import requests
import requests.exceptions
import pytest
import web_monitoring.db as wdb
import uuid

URL = 'https://www3.epa.gov/climatechange/impacts/society.html'
SITE = 'EPA - www3.epa.gov'
AGENCY = 'EPA'
PAGE_ID = '6c880bdd-c7a6-4bbf-a574-7d6479cc4fe8'
TO_VERSION_ID = '9342c121-cff0-4454-934f-d0f118508da1'

SETTINGS = {}
SETTINGS['db_url'] = "http://localhost:3000"
SETTINGS['db_email'] = "seed-admin@example.com"
SETTINGS['db_password'] = "PASSWORD"


def test_missing_creds():
    # Clear out settings to override settings from environment variables.
    for k in wdb.settings:
        wdb.settings[k] = None
    # Test that we fail early if no credenitals are entered.
    with pytest.raises(wdb.MissingCredentials):
        wdb.list_pages()


def test_list_pages():
    wdb.settings = SETTINGS
    res = wdb.list_pages()
    assert res['data']

    # Test chunk query parameters.
    res = wdb.list_pages(chunk_size=2)
    assert len(res['data']) == 2
    res = wdb.list_pages(chunk_size=5)
    assert len(res['data']) == 5

    # Test filtering query parameters.
    res = wdb.list_pages(url='__nonexistent__')
    assert len(res['data']) == 0
    res = wdb.list_pages(url=URL)
    assert len(res['data']) > 0
    res = wdb.list_pages(site='__nonexistent__')
    assert len(res['data']) == 0
    res = wdb.list_pages(site=SITE)
    assert len(res['data']) > 0
    res = wdb.list_pages(agency='__nonexistent__')
    assert len(res['data']) == 0
    res = wdb.list_pages(agency=AGENCY)
    assert len(res['data']) > 0


def test_get_page():
    wdb.settings = SETTINGS
    res = wdb.get_page(PAGE_ID)
    assert res['data']['uuid'] == PAGE_ID


def test_list_page_versions():
    wdb.settings = SETTINGS
    res = wdb.list_page_versions(PAGE_ID)
    assert all([v['page_uuid'] == PAGE_ID for v in res['data']])


def test_list_versions():
    wdb.settings = SETTINGS
    res = wdb.list_versions()
    assert res['data']


def test_get_version():
    wdb.settings = SETTINGS
    res = wdb.get_version(TO_VERSION_ID)
    assert res['data']['uuid'] == TO_VERSION_ID
    assert res['data']['page_uuid'] == PAGE_ID


def test_post_version():
    new_version_id = str(uuid.uuid4())
    now = datetime.now()
    wdb.post_version(page_id=PAGE_ID, uuid=new_version_id,
                     capture_time=now,
                     uri='http://example.com',
                     version_hash='placeholder',
                     source_type='test')
    data = wdb.get_version(new_version_id)['data']
    assert data['uuid'] == new_version_id
    assert data['page_uuid'] == PAGE_ID
    # Some floating-point error occurs in round-trip.
    assert (data['capture_time'] - now) < timedelta(seconds=0.001)
    assert data['source_type'] == 'test'


def test_post_versions():
    pass

def test_query_import_status():
    pass


def test_list_changes():
    # smoke test
    result = wdb.list_changes(PAGE_ID)


def test_get_change():
    # smoke test
    result = wdb.get_change(page_id=PAGE_ID,
                            to_version_id=TO_VERSION_ID)


def test_list_annotations():
    # smoke test
    result = wdb.list_annotations(page_id=PAGE_ID,
                                  to_version_id=TO_VERSION_ID)


def test_post_and_get_annotation():
    # smoke test
    annotation = {'foo': 'bar'}
    result = wdb.post_annotation(annotation,
                                 page_id=PAGE_ID,
                                 to_version_id=TO_VERSION_ID)
    annotation_id = result['data']['uuid']

    result2= wdb.get_annotation(annotation_id,
                                page_id=PAGE_ID,
                                to_version_id=TO_VERSION_ID)
    fetched_annotation = result2['data']['annotation']
    assert fetched_annotation == annotation
