from datetime import datetime, timezone
import pytest
from .._utils import memento_url_data


class TestMementoUrlData:
    def test_extracts_url(self):
        url, timestamp, mode = memento_url_data(
            'http://web.archive.org/web/20170813195036/'
            'https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'
        assert timestamp == datetime(2017, 8, 13, 19, 50, 36, tzinfo=timezone.utc)
        assert mode == ''

        url, timestamp, mode = memento_url_data(
            'http://web.archive.org/web/20170813195036id_/'
            'https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'
        assert timestamp == datetime(2017, 8, 13, 19, 50, 36, tzinfo=timezone.utc)
        assert mode == 'id_'

    def test_decodes_url(self):
        url, _, _ = memento_url_data(
            'http://web.archive.org/web/20150930233055id_/'
            'http%3A%2F%2Fwww.epa.gov%2Fenvironmentaljustice%2Fgrants%2Fej-smgrants.html%3Futm')
        assert url == 'http://www.epa.gov/environmentaljustice/grants/ej-smgrants.html?utm'

    def test_does_not_decode_query(self):
        url, _, _ = memento_url_data(
            'http://web.archive.org/web/20170813195036/'
            'https://arpa-e.energy.gov/?q=engage%2Fevents-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage%2Fevents-workshops'

    def test_raises_for_non_memento_urls(self):
        with pytest.raises(ValueError):
            memento_url_data('http://whatever.com')

    def test_raises_for_non_string_input(self):
        with pytest.raises(TypeError):
            memento_url_data(None)
