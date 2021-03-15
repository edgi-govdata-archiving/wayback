from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import pytest
import vcr
from .._utils import SessionClosedError
from .._client import (CdxRecord,
                       Mode,
                       WaybackSession,
                       WaybackClient)
from ..exceptions import (BlockedSiteError,
                          MementoPlaybackError,
                          NoMementoError,
                          RateLimitError)


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


def get_file(filepath):
    """Return the content of a file in the test_files directory."""
    full_path = Path(__file__).parent / 'test_files' / filepath
    with open(full_path, 'rb') as file:
        return file.read()


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


@pytest.mark.parametrize('parameter', ('output', 'fl', 'showDupeCount',
                                       'showSkipCount', 'lastSkipTimestamp',
                                       'showNumPages', 'showPagedIndex'))
def test_search_raises_for_unsupported_parameters(parameter):
    with pytest.raises(ValueError) as excinfo:
        with WaybackClient() as client:
            versions = client.search(**{'url': 'https://energystar.gov/',
                                        parameter: 'arbitrary_value'})
            next(versions)

    assert parameter in str(excinfo.value)


def test_search_removes_malformed_entries(requests_mock):
    """
    The CDX index contains many lines for things that can't actually be
    archived and will have no corresponding memento, like `mailto:` and `data:`
    URLs. We should be stripping these out.

    Because these are rare and hard to get all in a single CDX query that isn't
    *huge*, we use a made-up mock for this one instead of a VCR recording. All
    the lines in the mock file are lines from real CDX queries (we lost track
    of the specific cases that triggered that one, and it was *very* rare).
    """
    with open(Path(__file__).parent / 'test_files' / 'malformed_cdx.txt') as f:
        bad_cdx_data = f.read()

    with WaybackClient() as client:
        requests_mock.get('http://web.archive.org/cdx/search/cdx'
                          '?url=https%3A%2F%2Fepa.gov%2F%2A'
                          '&from=20200418000000&to=20200419000000'
                          '&showResumeKey=true&resolveRevisits=true',
                          [{'status_code': 200, 'text': bad_cdx_data}])
        records = client.search('https://epa.gov/*',
                                from_date=datetime(2020, 4, 18),
                                to_date=datetime(2020, 4, 19))

        assert 2 == len(list(records))


@ia_vcr.use_cassette()
def test_get_memento():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime=datetime(2017, 11, 24, 15, 13, 15))
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_date_datetime():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime=date(2017, 11, 24),
                                     exact=False)
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_string_datetime():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime='20171124151315')
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_inexact_string_datetime():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime='20171124151310',
                                     exact=False)
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_handles_non_utc_datetime():
    with WaybackClient() as client:
        # Note the offset between requested_time and memento.timestamp.
        requested_time = datetime(2017, 11, 24, 8, 13, 15,
                                  tzinfo=timezone(timedelta(hours=-7)))
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime=requested_time)

        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_invalid_datetime_type():
    with WaybackClient() as client:
        with pytest.raises(TypeError):
            client.get_memento('https://www.fws.gov/birds/',
                               datetime=True)


@ia_vcr.use_cassette()
def test_get_memento_with_requires_datetime_with_regular_url():
    with WaybackClient() as client:
        with pytest.raises(TypeError):
            client.get_memento('https://www.fws.gov/birds/')


@ia_vcr.use_cassette()
def test_get_memento_with_archive_url():
    with WaybackClient() as client:
        memento = client.get_memento(
            'http://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/')

        # Metadata About the Memento
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode
        assert 'http://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/' == memento.memento_url
        assert () == memento.history
        assert () == memento.debug_history

        # Archived HTTP Response
        assert 200 == memento.status_code
        assert memento.ok
        assert not memento.is_redirect
        assert {'Content-Type': 'text/html',
                'Date': 'Fri, 24 Nov 2017 15:13:14 GMT',
                'Strict-Transport-Security': 'max-age=31536000; includeSubDomains; preload',
                'Transfer-Encoding': 'chunked'} == memento.headers
        assert 'ISO-8859-1' == memento.encoding

        content = get_file('fws-gov-birds.txt')
        assert content == memento.content
        assert content.decode('iso-8859-1') == memento.text


@ia_vcr.use_cassette()
def test_get_memento_with_cdx_record():
    with WaybackClient() as client:
        record = CdxRecord('xyz',
                           datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc),
                           'https://www.fws.gov/birds/',
                           '-',
                           200,
                           'abc',
                           100,
                           'http://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/',
                           'http://web.archive.org/web/20171124151315/https://www.fws.gov/birds/')
        memento = client.get_memento(record)
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_mode():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime=datetime(2017, 11, 24, 15, 13, 15),
                                     mode=Mode.view)
        assert '' == memento.mode
        assert 'http://web.archive.org/web/20171124151315/https://www.fws.gov/birds/' == memento.memento_url

        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime=datetime(2017, 11, 24, 15, 13, 15))
        assert 'id_' == memento.mode
        assert 'http://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/' == memento.memento_url


@ia_vcr.use_cassette()
def test_get_memento_with_mode_string():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     datetime=datetime(2017, 11, 24, 15, 13, 15),
                                     mode='id_')
        assert 'id_' == memento.mode
        assert 'http://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/' == memento.memento_url


@ia_vcr.use_cassette()
def test_get_memento_with_mode_boolean_is_not_allowed():
    with WaybackClient() as client:
        with pytest.raises(TypeError):
            client.get_memento('https://www.fws.gov/birds/',
                               datetime=datetime(2017, 11, 24, 15, 13, 15),
                               mode=True)


@ia_vcr.use_cassette()
def test_get_memento_target_window():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     date(2017, 11, 1),
                                     exact=False,
                                     target_window=25 * 24 * 60 * 60)
        assert memento.timestamp == datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc)


@ia_vcr.use_cassette()
def test_get_memento_raises_when_memento_is_outside_target_window():
    with pytest.raises(MementoPlaybackError):
        with WaybackClient() as client:
            client.get_memento('https://www.fws.gov/birds/',
                               date(2017, 11, 1),
                               exact=False,
                               target_window=24 * 60 * 60)


@ia_vcr.use_cassette()
def test_get_memento_with_redirects():
    with WaybackClient() as client:
        memento = client.get_memento(
            'http://web.archive.org/web/20180808094144id_/https://www.epa.gov/ghgreporting/san5779-factsheet')
        assert len(memento.history) == 1        # memento redirects
        assert len(memento.debug_history) == 2  # actual HTTP redirects


@ia_vcr.use_cassette()
def test_get_memento_with_path_based_redirects():
    """
    Most redirects in Wayback redirect to a complete URL, with headers like:
        Location: http://web.archive.org/web/20201027215555id_/https://www.whitehouse.gov/administration
    But some include only an absolute path, e.g:
        Location: /web/20201027215555id_/https://www.whitehouse.gov/ostp/about/student/faqs
    This tests that we correctly handle the latter situation.
    """
    with WaybackClient() as client:
        memento = client.get_memento('https://www.whitehouse.gov/administration/eop/ostp/about/student/faqs',
                                     datetime(2020, 10, 27, 21, 55, 55))
        assert len(memento.history) == 1
        assert memento.url == memento.history[0].headers['Location']


@ia_vcr.use_cassette()
def test_get_memento_with_schemeless_redirects():
    """
    Most redirects in Wayback redirect to a complete URL, with headers like:
        Location: http://web.archive.org/web/20201027215555id_/https://www.whitehouse.gov/administration
    But some do not include a scheme:
        Location: //web.archive.org/web/20201102232816id_/https://www.census.gov/geo/gssi/
    This tests that we correctly handle the latter situation.
    """
    with WaybackClient() as client:
        memento = client.get_memento('https://www.census.gov/geography/gss-initiative.html',
                                     datetime(2020, 11, 2, 23, 28, 16))
        assert len(memento.history) == 1
        assert memento.url == memento.history[0].headers['Location']


@ia_vcr.use_cassette()
def test_get_memento_raises_for_mementos_that_redirect_in_a_loop():
    with WaybackClient() as client:
        with pytest.raises(MementoPlaybackError):
            client.get_memento(
                'https://link.springer.com/article/10.1007/s00382-012-1331-2',
                '20200925075402')


@ia_vcr.use_cassette()
def test_get_memento_should_fail_for_non_playbackable_mementos():
    with WaybackClient() as client:
        with pytest.raises(MementoPlaybackError):
            client.get_memento('https://www.fws.gov/birds/', '20170929002712')


@ia_vcr.use_cassette()
def test_get_memento_raises_blocked_error():
    with WaybackClient() as client:
        with pytest.raises(BlockedSiteError):
            client.get_memento('https://nationalpost.com/health/', '20170929002712')


@ia_vcr.use_cassette()
def test_get_memento_raises_no_memento_error():
    with WaybackClient() as client:
        with pytest.raises(NoMementoError):
            client.get_memento('https://this-is-not-real-url.whatever/',
                               '20170929002712')


@ia_vcr.use_cassette()
def test_get_memento_follows_historical_redirects():
    with WaybackClient() as client:
        # In February 2020, https://www.epa.gov/climatechange redirected to:
        #   https://www.epa.gov/sites/production/files/signpost/cc.html
        #
        # What should happen here under the hood:
        # http://web.archive.org/web/20200201020357id_/http://epa.gov/climatechange
        #   Is not a memento, and sends us to:
        #   http://web.archive.org/web/20200201023757id_/https://www.epa.gov/climatechange
        #     Which is a memento of a redirect to:
        #     http://web.archive.org/web/20200201023757id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        #       ...which is not a memento, and redirects to:
        #       http://web.archive.org/web/20200201024405id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        start_url = ('http://web.archive.org/web/20200201020357id_/'
                     'http://epa.gov/climatechange')
        target = ('http://web.archive.org/web/20200201024405id_/'
                  'https://www.epa.gov/sites/production/files/signpost/cc.html')
        memento = client.get_memento(start_url, exact=False)
        assert 'https://www.epa.gov/sites/production/files/signpost/cc.html' == memento.url
        assert target == memento.memento_url
        assert len(memento.history) == 1
        assert len(memento.debug_history) == 3


@ia_vcr.use_cassette()
def test_get_memento_follow_redirects_does_not_follow_historical_redirects():
    with WaybackClient() as client:
        # In February 2020, https://www.epa.gov/climatechange redirected to:
        #   https://www.epa.gov/sites/production/files/signpost/cc.html
        #
        # What should happen here under the hood:
        # http://web.archive.org/web/20200201020357id_/http://epa.gov/climatechange
        #   Is not a memento, and sends us to:
        #   http://web.archive.org/web/20200201023757id_/https://www.epa.gov/climatechange
        #     Which is a memento of a redirect. Because follow_redirects=False,
        #     we should *not* follow it to:
        #     http://web.archive.org/web/20200201023757id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        #       ...and then to:
        #       http://web.archive.org/web/20200201024405id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        start_url = ('http://web.archive.org/web/20200201020357id_/'
                     'http://epa.gov/climatechange')
        target = ('http://web.archive.org/web/20200201023757id_/'
                  'https://www.epa.gov/climatechange')
        memento = client.get_memento(start_url, exact=False, follow_redirects=False)
        assert 'https://www.epa.gov/climatechange' == memento.url
        assert target == memento.memento_url
        assert memento.status_code == 301
        assert 'https://www.epa.gov/sites/production/files/signpost/cc.html' == memento.headers['Location']
        assert len(memento.history) == 0
        assert len(memento.debug_history) == 1


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
