from datetime import datetime, timezone
import pytest
import time
from .._utils import memento_url_data, rate_limited


class TestMementoUrlData:
    def test_extracts_url(self):
        url, timestamp, mode = memento_url_data(
            'https://web.archive.org/web/20170813195036/'
            'https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'
        assert timestamp == datetime(2017, 8, 13, 19, 50, 36, tzinfo=timezone.utc)
        assert mode == ''

        url, timestamp, mode = memento_url_data(
            'https://web.archive.org/web/20170813195036id_/'
            'https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'
        assert timestamp == datetime(2017, 8, 13, 19, 50, 36, tzinfo=timezone.utc)
        assert mode == 'id_'

    def test_decodes_url(self):
        url, _, _ = memento_url_data(
            'https://web.archive.org/web/20150930233055id_/'
            'http%3A%2F%2Fwww.epa.gov%2Fenvironmentaljustice%2Fgrants%2Fej-smgrants.html%3Futm')
        assert url == 'http://www.epa.gov/environmentaljustice/grants/ej-smgrants.html?utm'

    def test_does_not_decode_query(self):
        url, _, _ = memento_url_data(
            'https://web.archive.org/web/20170813195036/'
            'https://arpa-e.energy.gov/?q=engage%2Fevents-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage%2Fevents-workshops'

    def test_raises_for_non_memento_urls(self):
        with pytest.raises(ValueError):
            memento_url_data('http://whatever.com')

    def test_raises_for_non_string_input(self):
        with pytest.raises(TypeError):
            memento_url_data(None)


class TestRateLimited:

    def test_call_per_seconds(self):
        """Test that the rate limit is accurately applied.
        It also checks that two rate limits applied sequentially do not interfere with another."""
        start_time = time.time()
        for i in range(4):
            with rate_limited(calls_per_second=3, group='cps1'):
                pass
        assert 1.0 <= time.time() - start_time <= 1.1

        start_time = time.time()
        for i in range(3):
            with rate_limited(calls_per_second=1, group='cps2'):
                pass
        assert 2.0 <= time.time() - start_time <= 2.1

        start_time = time.time()
        for i in range(3):
            with rate_limited(calls_per_second=0, group='cps3'):
                pass
        assert 0 <= time.time() - start_time <= 0.1

    def test_simultaneous_ratelimits(self):
        """Check that multiple rate limits do not interfere with another."""
        start_time = time.time()
        # The first loop should take 1 second, as it waits on the sim1 lock,
        # the second loop 0.66 seconds, since it waits twice on sim2.
        for i in range(2):
            with rate_limited(calls_per_second=1, group='sim1'):
                for j in range(3):
                    with rate_limited(calls_per_second=3, group='sim2'):
                        pass
        assert 1.66 <= time.time() - start_time <= 1.7
