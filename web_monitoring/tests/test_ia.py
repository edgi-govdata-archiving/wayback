from datetime import datetime
from web_monitoring.internetarchive import list_versions


def test_list_versions():
    pairs = list_versions('nasa.gov')
    dt, url = next(pairs)
    assert dt == datetime(1996, 12, 31, 23, 58, 47)

    # Exhaust the generator and make sure not entries trigger errors.
    list(pairs)


def test_list_versions_multipage(): 
    # cnn.com has enough 'mementos' to span multiple pages and exercise the
    # multi-page code path.
    pairs = list_versions('cnn.com')

    # Exhaust the generator and make sure not entries trigger errors.
    list(pairs)
