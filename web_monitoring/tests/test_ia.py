from datetime import datetime
import pytest
from web_monitoring.internetarchive import (list_versions,
                                            original_url_for_memento,
                                            timestamped_uri_to_version,
                                            MementoPlaybackError)


def test_list_versions():
    versions = list_versions('nasa.gov',
                             from_date=datetime(1996, 10, 1),
                             to_date=datetime(1997, 2, 1))
    version = next(versions)
    assert version.date == datetime(1996, 12, 31, 23, 58, 47)

    # Exhaust the generator and make sure no entries trigger errors.
    list(versions)


def test_list_versions_multipage():
    # Set page size limits low enough to guarantee multiple pages
    versions = list_versions('cnn.com',
                             from_date=datetime(2001, 4, 10),
                             to_date=datetime(2001, 4, 15),
                             cdx_params={'limit': 10})

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


def test_timestamped_uri_to_version():
    version = timestamped_uri_to_version(datetime(2017, 11, 24, 15, 13, 15),
                                         'http://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/',
                                         url='https://www.fws.gov/birds/')
    assert isinstance(version, dict)
    assert version['page_url'] == 'https://www.fws.gov/birds/'


def test_timestamped_uri_to_version_works_with_redirects():
    version = timestamped_uri_to_version(datetime(2018, 8, 8, 9, 41, 44),
                                         'http://web.archive.org/web/20180808094144id_/https://www.epa.gov/ghgreporting/san5779-factsheet',
                                         url='https://www.epa.gov/ghgreporting/san5779-factsheet')
    assert isinstance(version, dict)
    assert version['page_url'] == 'https://www.epa.gov/ghgreporting/san5779-factsheet'
    assert len(version['source_metadata']['redirects']) == 3


def test_timestamped_uri_to_version_should_fail_for_non_playbackable_mementos():
    with pytest.raises(MementoPlaybackError):
        timestamped_uri_to_version(datetime(2017, 9, 29, 0, 27, 12),
                                   'http://web.archive.org/web/20170929002712id_/https://www.fws.gov/birds/',
                                   url='https://www.fws.gov/birds/')
