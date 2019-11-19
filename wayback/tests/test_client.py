from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
import vcr
from .._utils import SessionClosedError
from .._client import (WaybackSession,
                       WaybackClient,
                       original_url_for_memento,
                       MementoPlaybackError)


# This stashes HTTP responses in JSON files (one per test) so that an actual
# server does not have to be running.
cassette_library_dir = str(Path(__file__).parent / Path('cassettes/'))
ia_vcr = vcr.VCR(
         serializer='yaml',
         cassette_library_dir=cassette_library_dir,
         record_mode='once',
         match_on=['uri', 'method'],
)


@ia_vcr.use_cassette()
def test_search():
    with WaybackClient() as client:
        versions = client.search('nasa.gov',
                                 from_date=datetime(1996, 10, 1),
                                 to_date=datetime(1997, 2, 1))
        version = next(versions)
        assert version.timestamp == datetime(1996, 12, 31, 23, 58, 47)

        # Exhaust the generator and make sure no entries trigger errors.
        list(versions)


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
        assert version.timestamp == datetime(1996, 12, 31, 23, 58, 47)

        # Search using UTC - 5, equivalent to (1997, 1, 1, 4, ...) in UTC
        # so that we miss the result above and expect a different, later one.
        tzinfo = timezone(timedelta(hours=-5))
        t0 = datetime(1996, 12, 31, 23, 58, 47, tzinfo=tzinfo)
        versions = client.search('nasa.gov',
                                 from_date=t0)
        version = next(versions)
        assert version.timestamp == datetime(1997, 6, 5, 23, 5, 59)


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
        assert len(response.history) == 2  # redirects


@ia_vcr.use_cassette()
def test_get_memento_should_fail_for_non_playbackable_mementos():
    with WaybackClient() as client:
        with pytest.raises(MementoPlaybackError):
            client.get_memento(
                'http://web.archive.org/web/20170929002712id_/https://www.fws.gov/birds/')


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
