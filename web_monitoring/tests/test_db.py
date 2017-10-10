# This module expects a local deployment of web-monitoring-db to be running
# with the default settings.

# The purpose is to test that the Python API can exercise all parts of the REST
# API. It is not meant to thoroughly check the correctness of the REST API.
from datetime import datetime, timedelta
import os
import pytest
import web_monitoring.db as wdb
import vcr


# This stashes web-monitoring-dbserver responses in JSON files (one per test)
# so that an actual server does not have to be running.
cassette_library_dir = os.path.join(os.path.dirname(__file__), 'cassettes')
db_vcr = vcr.VCR(
         serializer='json',
         cassette_library_dir=cassette_library_dir,
         record_mode='once',
         match_on=['uri', 'method'],
)


# Refers to real data that is part of the 'seed' dataset in web-monitoring-db
URL = 'https://www3.epa.gov/climatechange/impacts/society.html'
SITE = 'EPA - www3.epa.gov'
AGENCY = 'EPA'
PAGE_ID = '6c880bdd-c7a6-4bbf-a574-7d6479cc4fe8'
TO_VERSION_ID = '9342c121-cff0-4454-934f-d0f118508da1'
VERSIONISTA_ID = '10329339'

# The only matters when re-recording the tests for vcr.
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


@db_vcr.use_cassette()
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


@db_vcr.use_cassette()
def test_get_page():
    wdb.settings = SETTINGS
    res = wdb.get_page(PAGE_ID)
    assert res['data']['uuid'] == PAGE_ID


@db_vcr.use_cassette()
def test_list_page_versions():
    wdb.settings = SETTINGS
    res = wdb.list_page_versions(PAGE_ID)
    assert all([v['page_uuid'] == PAGE_ID for v in res['data']])


@db_vcr.use_cassette()
def test_list_versions():
    wdb.settings = SETTINGS
    res = wdb.list_versions()
    assert res['data']


@db_vcr.use_cassette()
def test_get_version():
    wdb.settings = SETTINGS
    res = wdb.get_version(TO_VERSION_ID)
    assert res['data']['uuid'] == TO_VERSION_ID
    assert res['data']['page_uuid'] == PAGE_ID


@db_vcr.use_cassette()
def test_get_version_by_versionista_id():
    wdb.settings = SETTINGS
    res = wdb.get_version_by_versionista_id(VERSIONISTA_ID)
    assert res['data']['uuid'] == TO_VERSION_ID
    assert res['data']['page_uuid'] == PAGE_ID


@db_vcr.use_cassette()
def test_get_version_by_versionista_id_failure():
    with pytest.raises(ValueError):
        wdb.get_version_by_versionista_id('__nonexistent__')


@db_vcr.use_cassette()
def test_get_version_uri_from_versionista():
    wdb.settings = SETTINGS
    # smoke test (because URI is installation-dependent)
    wdb.get_version_uri(VERSIONISTA_ID, id_type='source')


@db_vcr.use_cassette()
def test_get_version_uri_from_db():
    wdb.settings = SETTINGS
    # smoke test (because URI is installation-dependent)
    wdb.get_version_uri(TO_VERSION_ID, id_type='db')


@db_vcr.use_cassette()
def test_post_version():
    wdb.settings = SETTINGS
    new_version_id = '06620776-d347-4abd-a423-a871620299b2'
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


@db_vcr.use_cassette()
def test_list_changes():
    # smoke test
    wdb.settings = SETTINGS
    wdb.list_changes(PAGE_ID)


@db_vcr.use_cassette()
def test_get_change():
    # smoke test
    wdb.settings = SETTINGS
    wdb.get_change(page_id=PAGE_ID,
                   to_version_id=TO_VERSION_ID)


@db_vcr.use_cassette()
def test_list_annotations():
    # smoke test
    wdb.settings = SETTINGS
    wdb.list_annotations(page_id=PAGE_ID,
                         to_version_id=TO_VERSION_ID)



mutable_stash = []  # used to pass info from this test to the next


@db_vcr.use_cassette()
def test_post_annotation():
    # smoke test
    wdb.settings = SETTINGS
    annotation = {'foo': 'bar'}
    result = wdb.post_annotation(annotation,
                                 page_id=PAGE_ID,
                                 to_version_id=TO_VERSION_ID)
    annotation_id = result['data']['uuid']
    mutable_stash.append(annotation_id)


@db_vcr.use_cassette()
def test_get_annotation():
    wdb.settings = SETTINGS
    annotation_id = mutable_stash.pop()
    result = wdb.get_annotation(annotation_id,
                                page_id=PAGE_ID,
                                to_version_id=TO_VERSION_ID)
    fetched_annotation = result['data']['annotation']
    annotation = {'foo': 'bar'}
    assert fetched_annotation == annotation
