from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import pytest
import vcr
from .._utils import SessionClosedError
from .._client import (WaybackSession,
                       WaybackClient,
                       original_url_for_memento)
from ..exceptions import MementoPlaybackError, RateLimitError, BlockedSiteError


# This stashes HTTP responses in JSON files (one per test) so that an actual
# server does not have to be running.
cassette_library_dir = str(Path(__file__).parent / Path('cassettes/'))
ia_vcr = vcr.VCR(
         serializer='yaml',
         cassette_library_dir=cassette_library_dir,
         record_mode='once',
         match_on=['uri', 'method'],
)


# It's tough to capture a rate-limited response. Using VCR to do so would
# require an overly-complex test and a very verbose recording (with lots of
# excess requests & responses in order to breach the limit). So this is simply
# a manual mock based on an actual rate-limited response.
WAYBACK_RATE_LIMIT_ERROR = dict(
    status_code=429,
    headers={
        'Server': 'nginx/1.15.8',
        'Date': 'Fri, 19 Jun 2020 23:44:42 GMT',
        'Content-Type': 'text/html',
        'Transfer-Encoding': 'chunked',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        # NOTE: Wayback does not currently include this header. It's optional,
        # and is included here to test whether we will handle it nicely if the
        # Wayback Machine ever adds it.
        # https://tools.ietf.org/html/rfc6585#section-4
        'Retry-After': '10'
    },
    text='''<html><body><h1>429 Too Many Requests</h1>
You have sent too many requests in a given amount of time.
</body></html>'''
)


@ia_vcr.use_cassette()
def test_search():
    with WaybackClient() as client:
        versions = client.search('nasa.gov',
                                 from_date=datetime(1996, 10, 1),
                                 to_date=datetime(1997, 2, 1))
        for v in versions:
            assert v.timestamp >= datetime(1996, 10, 1, tzinfo=timezone.utc)
            assert v.timestamp <= datetime(1997, 2, 1, tzinfo=timezone.utc)


@ia_vcr.use_cassette()
def test_search_with_date():
    with WaybackClient() as client:
        versions = client.search('dw.com',
                                 from_date=date(2019, 10, 1),
                                 to_date=date(2020, 3, 1))
        for v in versions:
            assert v.timestamp >= datetime(2019, 10, 1, tzinfo=timezone.utc)
            assert v.timestamp <= datetime(2020, 3, 1, tzinfo=timezone.utc)


@ia_vcr.use_cassette()
def test_search_with_timezone():
    with WaybackClient() as client:
        # Search using UTC, equivalent to the test above where we provide a
        # datetime with no timezone.
        tzinfo = timezone(timedelta(hours=0))
        t0 = datetime(1996, 12, 31, 23, 58, 47, tzinfo=tzinfo)
        versions = client.search('nasa.gov',
                                 from_date=t0)
        version = next(versions)
        assert version.timestamp == datetime(1996, 12, 31, 23, 58, 47,
                                             tzinfo=timezone.utc)

        # Search using UTC - 5, equivalent to (1997, 1, 1, 4, ...) in UTC
        # so that we miss the result above and expect a different, later one.
        tzinfo = timezone(timedelta(hours=-5))
        t0 = datetime(1996, 12, 31, 23, 58, 47, tzinfo=tzinfo)
        versions = client.search('nasa.gov',
                                 from_date=t0)
        version = next(versions)
        assert version.timestamp == datetime(1997, 6, 5, 23, 5, 59,
                                             tzinfo=timezone.utc)


@ia_vcr.use_cassette()
def test_search_multipage():
    # Set page size limits low enough to guarantee multiple pages
    with WaybackClient() as client:
        versions = client.search('cnn.com',
                                 from_date=datetime(2001, 4, 10),
                                 to_date=datetime(2001, 5, 10),
                                 limit=25)

        # Exhaust the generator and make sure no entries trigger errors.
        list(versions)


@ia_vcr.use_cassette()
def test_search_cannot_iterate_after_session_closing():
    with pytest.raises(SessionClosedError):
        with WaybackClient() as client:
            versions = client.search('nasa.gov',
                                     from_date=datetime(1996, 10, 1),
                                     to_date=datetime(1997, 2, 1))

        next(versions)


@ia_vcr.use_cassette()
def test_search_does_not_repeat_results():
    with WaybackClient() as client:
        versions = client.search('energystar.gov/',
                                 from_date=datetime(2020, 6, 12),
                                 to_date=datetime(2020, 6, 13))
        previous = None
        for version in versions:
            assert version != previous
            previous = version


@ia_vcr.use_cassette()
def test_search_raises_for_blocked_urls():
    with pytest.raises(BlockedSiteError):
        with WaybackClient() as client:
            versions = client.search('https://nationalpost.com/health',
                                     from_date=datetime(2019, 10, 1),
                                     to_date=datetime(2019, 10, 2))
            next(versions)


class TestOriginalUrlForMemento:
    def test_extracts_url(self):
        url = original_url_for_memento(
            'http://web.archive.org/web/20170813195036/'
            'https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'

        url = original_url_for_memento(
            'http://web.archive.org/web/20170813195036id_/'
            'https://arpa-e.energy.gov/?q=engage/events-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage/events-workshops'

    def test_decodes_url(self):
        url = original_url_for_memento(
            'http://web.archive.org/web/20150930233055id_/'
            'http%3A%2F%2Fwww.epa.gov%2Fenvironmentaljustice%2Fgrants%2Fej-smgrants.html%3Futm')
        assert url == 'http://www.epa.gov/environmentaljustice/grants/ej-smgrants.html?utm'

    def test_does_not_decode_query(self):
        url = original_url_for_memento(
            'http://web.archive.org/web/20170813195036/'
            'https://arpa-e.energy.gov/?q=engage%2Fevents-workshops')
        assert url == 'https://arpa-e.energy.gov/?q=engage%2Fevents-workshops'

    def test_raises_for_non_memento_urls(self):
        with pytest.raises(ValueError):
            original_url_for_memento('http://whatever.com')

    def test_raises_for_non_string_input(self):
        with pytest.raises(TypeError):
            original_url_for_memento(None)


@ia_vcr.use_cassette()
def test_get_memento():
    with WaybackClient() as client:
        response = client.get_memento(
            'http://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/')
        assert 'Link' in response.headers
        original, *_ = response.headers['Link'].split(',', 1)
        assert original == '<https://www.fws.gov/birds/>; rel="original"'


@ia_vcr.use_cassette()
def test_get_memento_with_redirects():
    with WaybackClient() as client:
        response = client.get_memento(
            'http://web.archive.org/web/20180808094144id_/https://www.epa.gov/ghgreporting/san5779-factsheet')
        assert len(response.history) == 1        # memento redirects
        assert len(response.debug_history) == 2  # actual HTTP redirects


@ia_vcr.use_cassette()
def test_get_memento_should_fail_for_non_playbackable_mementos():
    with WaybackClient() as client:
        with pytest.raises(MementoPlaybackError):
            client.get_memento(
                'http://web.archive.org/web/20170929002712id_/https://www.fws.gov/birds/')


@ia_vcr.use_cassette()
def test_get_memento_raises_blocked_error():
    with WaybackClient() as client:
        with pytest.raises(BlockedSiteError):
            client.get_memento(
                'http://web.archive.org/web/20170929002712id_/https://nationalpost.com/health/')


class TestWaybackSession:
    def test_request_retries(self, requests_mock):
        requests_mock.get('http://test.com', [{'text': 'bad1', 'status_code': 503},
                                              {'text': 'bad2', 'status_code': 503},
                                              {'text': 'good', 'status_code': 200}])
        session = WaybackSession(retries=2, backoff=0.1)
        response = session.request('GET', 'http://test.com')
        assert response.ok

        session.close()

    def test_stops_after_given_retries(self, requests_mock):
        requests_mock.get('http://test.com', [{'text': 'bad1', 'status_code': 503},
                                              {'text': 'bad2', 'status_code': 503},
                                              {'text': 'good', 'status_code': 200}])
        session = WaybackSession(retries=1, backoff=0.1)
        response = session.request('GET', 'http://test.com')
        assert response.status_code == 503
        assert response.text == 'bad2'

    def test_only_retries_some_errors(self, requests_mock):
        requests_mock.get('http://test.com', [{'text': 'bad1', 'status_code': 400},
                                              {'text': 'good', 'status_code': 200}])
        session = WaybackSession(retries=1, backoff=0.1)
        response = session.request('GET', 'http://test.com')
        assert response.status_code == 400

    def test_raises_rate_limit_error(self, requests_mock):
        requests_mock.get('http://test.com', [WAYBACK_RATE_LIMIT_ERROR])
        with pytest.raises(RateLimitError):
            session = WaybackSession(retries=0)
            session.request('GET', 'http://test.com')

    def test_rate_limit_error_includes_retry_after(self, requests_mock):
        requests_mock.get('http://test.com', [WAYBACK_RATE_LIMIT_ERROR])
        with pytest.raises(RateLimitError) as excinfo:
            session = WaybackSession(retries=0)
            session.request('GET', 'http://test.com')

        assert excinfo.value.retry_after == 10
