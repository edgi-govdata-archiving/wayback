import web_monitoring.db as wdb
import pytest

url1 = 'https://edgi-versionista-archive.s3.amazonaws.com/versionista1/74005-6249585/version-9671845.html'
version_id = '9671845'

page_id = 'c43413cb-2939-4d34-bb0f-e8ddac22e9e2'
from_version_id = 'e7d1062b-e5d5-42b8-8a2d-e3b7c015f7f4'
to_version_id = '8693b164-3814-494c-b3c2-a86164b42ffe'
data_id = 'f3781581-0bc0-4383-981d-a52a684b8e9f'
#annotations = {'indiv_1' : false}

@pytest.mark.skip(reason="test not implemented")
def test_post_versions():
    pass

@pytest.mark.skip(reason="test not implemented")
def test_query_import_status():
    pass

def test_get_version_uri():
    result = wdb.get_version_uri(version_id=version_id, id_type='source')
    assert result == url1

def test_get_changes():
    response = wdb.get_changes(page_id=page_id,
                               from_version_id=from_version_id,
                               to_version_id=to_version_id)

    assert response.ok
    result = response.json()
    assert result['data']['uuid'] == data_id

@pytest.mark.skip(reason="test not working, need alternate test")
def test_post_changes():

    """
    response = wdb.post_changes(page_id=page_id,
                                from_version_id=from_version_id,
                                to_version_id=to_version_id,
                                annotations=annotations)
    assert response.ok
    """
    pass



