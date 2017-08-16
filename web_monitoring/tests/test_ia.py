from datetime import datetime
from web_monitoring.internetarchive import list_versions


def test_list_versions():
    versions = list_versions('nasa.gov')
    version = next(versions)
    assert version.date == datetime(1996, 12, 31, 23, 58, 47)

    # Exhaust the generator and make sure no entries trigger errors.
    list(versions)


def test_list_versions_multipage():
    # cnn.com has enough 'mementos' to span multiple pages and exercise the
    # multi-page code path.
    versions = list_versions('cnn.com')

    # Exhaust the generator and make sure no entries trigger errors.
    list(versions)
