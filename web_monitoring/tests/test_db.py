# This module expects a local deployment of web-monitoring-db to be running
# with the default settings.

# The purpose is to test that the Python API can exercise all parts of the REST
# API. It is not meant to thoroughly check the correctness of the REST API.
from datetime import datetime, timedelta, timezone
import os
import pytest
from web_monitoring.db import Client, MissingCredentials
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
global_stash = {}  # used to pass info between tests


# Refers to real data that is part of the 'seed' dataset in web-monitoring-db
URL = 'https://www3.epa.gov/climatechange/impacts/society.html'
SITE = 'EPA - www3.epa.gov'
AGENCY = 'EPA'
PAGE_ID = '6c880bdd-c7a6-4bbf-a574-7d6479cc4fe8'
TO_VERSION_ID = '9342c121-cff0-4454-934f-d0f118508da1'
VERSIONISTA_ID = '10329339'

# This is used in new Versions that we add.
TIME = datetime(2017, 1, 1, tzinfo=timezone.utc)

# The only matters when re-recording the tests for vcr.
AUTH = {'url': "http://localhost:3000",
        'email': "seed-admin@example.com",
        'password': "PASSWORD"}


def test_missing_creds():
    try:
        env = os.environ.copy()
        os.environ.clear()
        with pytest.raises(MissingCredentials):
            Client.from_env()
        os.environ.update({'WEB_MONITORING_DB_URL': AUTH['url'],
                           'WEB_MONITORING_DB_EMAIL': AUTH['email'],
                           'WEB_MONITORING_DB_PASSWORD': AUTH['password']})
        Client.from_env()  # should work
    finally:
        os.environ.update(env)


@db_vcr.use_cassette()
def test_list_pages():
    cli = Client(**AUTH)
    res = cli.list_pages()
    assert res['data']

    # Test chunk query parameters.
    res = cli.list_pages(chunk_size=2)
    assert len(res['data']) == 2
    res = cli.list_pages(chunk_size=5)
    assert len(res['data']) == 5

    # Test filtering query parameters.
    res = cli.list_pages(url='__nonexistent__')
    assert len(res['data']) == 0
    res = cli.list_pages(url=URL)
    assert len(res['data']) > 0
    res = cli.list_pages(site='__nonexistent__')
    assert len(res['data']) == 0
    res = cli.list_pages(site=SITE)
    assert len(res['data']) > 0
    res = cli.list_pages(agency='__nonexistent__')
    assert len(res['data']) == 0
    res = cli.list_pages(agency=AGENCY)
    assert len(res['data']) > 0


@db_vcr.use_cassette()
def test_get_page():
    cli = Client(**AUTH)
    res = cli.get_page(PAGE_ID)
    assert res['data']['uuid'] == PAGE_ID


@db_vcr.use_cassette()
def test_list_page_versions():
    cli = Client(**AUTH)
    res = cli.list_versions(page_id=PAGE_ID)
    assert all([v['page_uuid'] == PAGE_ID for v in res['data']])


@db_vcr.use_cassette()
def test_list_versions():
    cli = Client(**AUTH)
    res = cli.list_versions()
    assert res['data']


@db_vcr.use_cassette()
def test_get_version():
    cli = Client(**AUTH)
    res = cli.get_version(TO_VERSION_ID)
    assert res['data']['uuid'] == TO_VERSION_ID
    assert res['data']['page_uuid'] == PAGE_ID


@db_vcr.use_cassette()
def test_get_version_by_versionista_id():
    cli = Client(**AUTH)
    res = cli.get_version_by_versionista_id(VERSIONISTA_ID)
    assert res['data']['uuid'] == TO_VERSION_ID
    assert res['data']['page_uuid'] == PAGE_ID


@db_vcr.use_cassette()
def test_get_version_by_versionista_id_failure():
    cli = Client(**AUTH)
    with pytest.raises(ValueError):
        cli.get_version_by_versionista_id('__nonexistent__')


@db_vcr.use_cassette()
def test_add_version():
    cli = Client(**AUTH)
    new_version_id = '06620776-d347-4abd-a423-a871620299b5'
    cli.add_version(page_id=PAGE_ID, uuid=new_version_id,
                    capture_time=TIME,
                    uri='http://example.com',
                    hash='hash_placeholder',
                    title='title_placeholder',
                    source_type='test')
    data = cli.get_version(new_version_id)['data']
    assert data['uuid'] == new_version_id
    assert data['page_uuid'] == PAGE_ID
    # Some floating-point error occurs in round-trip.
    epsilon = timedelta(seconds=0.001)
    assert data['capture_time'] - TIME < epsilon
    assert data['source_type'] == 'test'
    assert data['title'] == 'title_placeholder'


@db_vcr.use_cassette()
def test_add_versions():
    cli = Client(**AUTH)
    new_version_ids = [
        'afe59db6-e7f7-4f34-a54f-54b7cf83dcf2',
        '26cf9f7c-ce36-4d47-8d8c-86d44e1d1d82',
        '4d04d19e-6d29-4d00-965f-b2b7fc320622',
        '64b3ed51-b9e4-40d7-9068-3c76306a6562',
        '85091741-b8f4-4ac8-8677-613403425ac2',
        'a1533b44-3378-4060-af60-3870ef132772',
        'a19b547a-26de-4610-bc61-32a85acea562',
        '24698ec1-d54a-40e6-ae88-d57472a92252',
        '6f2d3a12-3742-4755-b419-4c5ea3989382',
        'f133040c-7222-4189-aa7b-b155b7859ae2']
    versions = [dict(page_id=PAGE_ID, uuid=version_id,
                     capture_time=TIME,
                     uri='http://example.com',
                     hash='hash_placeholder',
                     title='title_placeholder',
                     source_type='test') for version_id in new_version_ids]
    import_id = cli.add_versions(versions)
    global_stash['import_id'] = import_id


@db_vcr.use_cassette()
def test_get_import_status():
    cli = Client(**AUTH)
    import_id = global_stash['import_id']
    cli.get_import_status(import_id)


@db_vcr.use_cassette()
def test_add_versions_batched():
    cli = Client(**AUTH)
    new_version_ids = [
        'd68c5521-0728-4098-96dd-e6330612f033',
        'db2932c4-413b-41f6-b73d-602faccf2f23',
        '4cfe3e9b-01b3-4a5f-bb45-e7657fc38863',
        'e1731130-569a-45a5-8db9-e58764e720d3',
        '901feef4-91b8-4140-8dcc-a414f52befb3',
        '4cd662bc-e322-463e-9fe1-12fbccb62ab3',
        '1d0e7eb7-4920-48b5-a810-d01e7ae27c53',
        '8b420ce3-ecc5-43e2-865a-b02c854f64d3',
        'ae23d4f2-ab34-43da-b58f-57c4ab8bdd53',
        'b8cc3d0f-f2eb-43ef-bfc7-d0b589ee7f23']
    versions = [dict(page_id=PAGE_ID, uuid=version_id,
                     capture_time=TIME,
                     uri='http://example.com',
                     hash='hash_placeholder',
                     title='title_placeholder',
                     source_type='test') for version_id in new_version_ids]
    import_ids = cli.add_versions_batched(versions, batch_size=5)
    global_stash['import_ids'] = import_ids


@db_vcr.use_cassette()
def test_monitor_batch_import_status():
    cli = Client(**AUTH)
    import_ids = global_stash['import_ids']
    errors = cli.monitor_batch_import_status(import_ids)
    assert not errors


@db_vcr.use_cassette()
def test_list_changes():
    cli = Client(**AUTH)
    # smoke test
    cli.list_changes(PAGE_ID)


@db_vcr.use_cassette()
def test_get_change():
    cli = Client(**AUTH)
    # smoke test
    cli.get_change(page_id=PAGE_ID,
                   to_version_id=TO_VERSION_ID)


@db_vcr.use_cassette()
def test_list_annotations():
    cli = Client(**AUTH)
    # smoke test
    cli.list_annotations(page_id=PAGE_ID,
                         to_version_id=TO_VERSION_ID)



@db_vcr.use_cassette()
def test_add_annotation():
    cli = Client(**AUTH)
    # smoke test
    annotation = {'foo': 'bar'}
    result = cli.add_annotation(annotation,
                                 page_id=PAGE_ID,
                                 to_version_id=TO_VERSION_ID)
    annotation_id = result['data']['uuid']
    global_stash['annotation_id'] = annotation_id


@db_vcr.use_cassette()
def test_get_annotation():
    cli = Client(**AUTH)
    annotation_id = global_stash['annotation_id']
    result = cli.get_annotation(annotation_id,
                                page_id=PAGE_ID,
                                to_version_id=TO_VERSION_ID)
    fetched_annotation = result['data']['annotation']
    annotation = {'foo': 'bar'}
    assert fetched_annotation == annotation
