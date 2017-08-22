from datetime import datetime
from web_monitoring.internetarchive import (list_versions,
                                            original_url_for_memento)


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


class TestOriginalUrlForMemento:
    def test_extracts_url(self):
        url = original_url_for_memento('http://web.archive.org/web/20170813195036/https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'

        url = original_url_for_memento('http://web.archive.org/web/20170813195036id_/https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'

    def test_decodes_url(self):
        url = original_url_for_memento('http://web.archive.org/web/20150930233055id_/http%3A%2F%2Fwww.epa.gov%2Fenvironmentaljustice%2Fgrants%2Fej-smgrants.html%3Futm')
        assert url == 'http://www.epa.gov/environmentaljustice/grants/ej-smgrants.html?utm'

    def test_does_not_decode_query(self):
        url = original_url_for_memento('http://web.archive.org/web/20170813195036/https://arpa-e.energy.gov/?q=engage%2Fevents-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage%2Fevents-workshops'
