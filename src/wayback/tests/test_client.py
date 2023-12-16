from datetime import date, datetime, timezone, timedelta
from io import BytesIO
from itertools import islice
from pathlib import Path
import time
import pytest
from unittest import mock
from urllib.parse import urlparse, ParseResult, parse_qs
from urllib3 import (HTTPConnectionPool,
                     HTTPResponse,
                     Timeout as Urllib3Timeout)
# The Header dict lives in a different place for urllib3 v2:
try:
    from urllib3 import HTTPHeaderDict
# vs. urllib3 v1:
except ImportError:
    from urllib3.response import HTTPHeaderDict

from .support import create_vcr
from .._client import (CdxRecord,
                       Mode,
                       WaybackSession,
                       WaybackClient,
                       DEFAULT_CDX_RATE_LIMIT,
                       DEFAULT_MEMENTO_RATE_LIMIT,
                       DEFAULT_TIMEMAP_RATE_LIMIT)
from ..exceptions import (BlockedSiteError,
                          MementoPlaybackError,
                          NoMementoError,
                          RateLimitError,
                          SessionClosedError)


ia_vcr = create_vcr()

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


@pytest.fixture(autouse=True)
def reset_default_rate_limits():
    DEFAULT_CDX_RATE_LIMIT.reset()
    DEFAULT_MEMENTO_RATE_LIMIT.reset()
    DEFAULT_TIMEMAP_RATE_LIMIT.reset()


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


@ia_vcr.use_cassette()
def test_search_with_filter():
    with WaybackClient() as client:
        # Check an unfiltered request to cover false positives.
        versions = client.search('nasa.gov/',
                                 match_type='prefix',
                                 limit=10,
                                 from_date=date(2022, 1, 1),
                                 to_date=date(2022, 2, 1))
        versions = list(islice(versions, 10))
        assert any((v.status_code == 200 for v in versions))

        # Then an actually filtered request.
        versions = client.search('nasa.gov/',
                                 match_type='prefix',
                                 limit=10,
                                 from_date=date(2022, 1, 1),
                                 to_date=date(2022, 2, 1),
                                 filter_field='statuscode:404')
        versions = list(islice(versions, 10))
        assert all((v.status_code == 404 for v in versions))


@ia_vcr.use_cassette()
def test_search_with_filter_list():
    with WaybackClient() as client:
        # Check an unfiltered request to cover false positives.
        versions = client.search('nasa.gov/',
                                 match_type='prefix',
                                 limit=10,
                                 from_date=date(2022, 1, 1),
                                 to_date=date(2022, 2, 1))
        versions = list(islice(versions, 10))
        assert any((v.status_code == 200 for v in versions))
        assert any(('feature' not in v.url for v in versions))

        # Then an actually filtered request.
        versions = client.search('nasa.gov/',
                                 match_type='prefix',
                                 limit=10,
                                 from_date=date(2022, 1, 1),
                                 to_date=date(2022, 2, 1),
                                 filter_field=['statuscode:404',
                                               'urlkey:.*feature.*'])
        versions = list(islice(versions, 10))
        assert all((v.status_code == 404 for v in versions))
        assert all(('feature' in v.url for v in versions))


@ia_vcr.use_cassette()
def test_search_with_filter_tuple():
    with WaybackClient() as client:
        # Then an actually filtered request.
        versions = client.search('nasa.gov/',
                                 match_type='prefix',
                                 limit=10,
                                 from_date=date(2022, 1, 1),
                                 to_date=date(2022, 2, 1),
                                 filter_field=('statuscode:404',
                                               'urlkey:.*feature.*'))
        versions = list(islice(versions, 10))
        assert all((v.status_code == 404 for v in versions))
        assert all(('feature' in v.url for v in versions))


class Urllib3MockManager:
    def __init__(self) -> None:
        self.responses = []

    def get(self, url, responses) -> None:
        url_info = urlparse(url)
        if url_info.path == '':
            url_info = url_info._replace(path='/')
        for index, response in enumerate(responses):
            repeat = True if index == len(responses) - 1 else False
            self.responses.append(('GET', url_info, response, repeat))

    def _compare_querystrings(self, actual, candidate):
        for k, v in candidate.items():
            if k not in actual or actual[k] != v:
                return False
        return True

    def urlopen(self, pool: HTTPConnectionPool, method, url, *args, preload_content: bool = True, **kwargs):
        opened_url = urlparse(url)
        opened_path = opened_url.path or '/'
        opened_query = parse_qs(opened_url.query)
        for index, candidate in enumerate(self.responses):
            candidate_url: ParseResult = candidate[1]
            if (
                method == candidate[0]
                and (not candidate_url.scheme or candidate_url.scheme == pool.scheme)
                and (not candidate_url.hostname or candidate_url.hostname == pool.host)
                and (not candidate_url.port or candidate_url.port == pool.port)
                and candidate_url.path == opened_path
                # This is cheap, ideally we'd parse the querystrings.
                # and parse_qs(candidate_url.query) == opened_query
                and self._compare_querystrings(opened_query, parse_qs(candidate_url.query))
            ):
                if not candidate[3]:
                    self.responses.pop(index)

                data = candidate[2]
                if data.get('exc'):
                    raise data['exc']()

                content = data.get('content')
                if content is None:
                    content = data.get('text', '').encode()

                return HTTPResponse(
                    body=BytesIO(content),
                    headers=HTTPHeaderDict(data.get('headers', {})),
                    status=data.get('status_code', 200),
                    decode_content=False,
                    preload_content=preload_content,
                )

        # No matches!
        raise RuntimeError(
            f"No HTTP mocks matched {method} {pool.scheme}://{pool.host}{url}"
        )


@pytest.fixture
def urllib3_mock(monkeypatch):
    manager = Urllib3MockManager()

    def urlopen_mock(self, method, url, *args, preload_content: bool = True, **kwargs):
        return manager.urlopen(self, method, url, *args, preload_content=preload_content, **kwargs)

    monkeypatch.setattr(
        "urllib3.connectionpool.HTTPConnectionPool.urlopen", urlopen_mock
    )

    return manager


def test_search_removes_malformed_entries(urllib3_mock):
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
        urllib3_mock.get('https://web.archive.org/cdx/search/cdx'
                         '?url=https%3A%2F%2Fepa.gov%2F%2A'
                         '&limit=1000'
                         '&from=20200418000000&to=20200419000000'
                         '&showResumeKey=true&resolveRevisits=true',
                         [{'status_code': 200, 'text': bad_cdx_data}])
        records = client.search('https://epa.gov/*',
                                from_date=datetime(2020, 4, 18),
                                to_date=datetime(2020, 4, 19))

        assert 2 == len(list(records))


def test_search_handles_no_length_cdx_records(urllib3_mock):
    """
    The CDX index can contain a "-" in lieu of an actual length, which can't be
    parsed into an int. We should handle this.

    Because these are rare and hard to get all in a single CDX query that isn't
    *huge*, we use a made-up mock for this one instead of a VCR recording.
    """
    with open(Path(__file__).parent / 'test_files' / 'zero_length_cdx.txt') as f:
        bad_cdx_data = f.read()

    with WaybackClient() as client:
        urllib3_mock.get('https://web.archive.org/cdx/search/cdx'
                         '?url=www.cnn.com%2F%2A'
                         '&matchType=domain&filter=statuscode%3A200'
                         '&showResumeKey=true&resolveRevisits=true',
                         [{'status_code': 200, 'text': bad_cdx_data}])
        records = client.search('www.cnn.com/*',
                                match_type="domain",
                                filter_field="statuscode:200")

        record_list = list(records)
        assert 5 == len(record_list)
        for record in record_list[:4]:
            assert isinstance(record.length, int)
        assert record_list[-1].length is None


def test_search_handles_bad_timestamp_cdx_records(urllib3_mock):
    """
    The CDX index can contain a timestamp with an invalid day "00", which can't be
    parsed into an timestamp. We should handle this.

    Because these are rare and hard to get all in a single CDX query that isn't
    *huge*, we use a made-up mock for this one instead of a VCR recording.
    """
    with open(Path(__file__).parent / 'test_files' / 'bad_timestamp_cdx.txt') as f:
        bad_cdx_data = f.read()

    with WaybackClient() as client:
        urllib3_mock.get('https://web.archive.org/cdx/search/cdx'
                         '?url=www.usatoday.com%2F%2A'
                         '&limit=1000'
                         '&matchType=domain&filter=statuscode%3A200'
                         '&showResumeKey=true&resolveRevisits=true',
                         [{'status_code': 200, 'text': bad_cdx_data}])
        records = client.search('www.usatoday.com/*',
                                match_type="domain",
                                filter_field="statuscode:200")

        record_list = list(records)
        assert 5 == len(record_list)

        # 00 month in 20000012170449 gets rewritten to 20001217044900
        assert record_list[3].timestamp.month == 12

        # 00 day in 20000800241623 gets rewritten to 20000824162300
        assert record_list[4].timestamp.day == 24


@ia_vcr.use_cassette()
def test_get_memento():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     timestamp=datetime(2017, 11, 24, 15, 13, 15))
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode
        assert memento.headers == {
            'Content-Type': 'text/html',
            'Date': 'Fri, 24 Nov 2017 15:13:14 GMT',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains; preload',
            'Transfer-Encoding': 'chunked'
        }
        assert memento.links == {
            'first memento': {
                'datetime': 'Wed, 23 Mar 2005 15:53:00 GMT',
                'rel': 'first memento',
                'url': 'https://web.archive.org/web/20050323155300id_/http://www.fws.gov:80/birds'
            },
            'last memento': {
                'datetime': 'Sun, 19 Mar 2023 07:02:36 GMT',
                'rel': 'last memento',
                'url': 'https://web.archive.org/web/20230319070236id_/http://fws.gov/birds/'
            },
            'prev memento': {
                'datetime': 'Fri, 29 Sep 2017 00:27:12 GMT',
                'rel': 'prev memento',
                'url': 'https://web.archive.org/web/20170929002712id_/https://www.fws.gov/birds/'
            },
            'next memento': {
                'datetime': 'Thu, 28 Dec 2017 22:21:43 GMT',
                'rel': 'next memento',
                'url': 'https://web.archive.org/web/20171228222143id_/https://www.fws.gov/birds/'
            },
            'memento': {
                'datetime': 'Fri, 24 Nov 2017 15:13:15 GMT',
                'rel': 'memento',
                'url': 'https://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/'
            },
            'original': {
                'rel': 'original',
                'url': 'https://www.fws.gov/birds/'
            },
            'timegate': {
                'rel': 'timegate',
                'url': 'https://web.archive.org/web/https://www.fws.gov/birds/'
            },
            'timemap': {
                'rel': 'timemap',
                'type': 'application/link-format',
                'url': 'https://web.archive.org/web/timemap/link/https://www.fws.gov/birds/'
            },
        }


@ia_vcr.use_cassette()
def test_get_memento_with_date_datetime():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     timestamp=date(2017, 11, 24),
                                     exact=False)
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_string_datetime():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     timestamp='20171124151315')
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_inexact_string_datetime():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     timestamp='20171124151310',
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
                                     timestamp=requested_time)

        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_invalid_datetime_type():
    with WaybackClient() as client:
        with pytest.raises(TypeError):
            client.get_memento('https://www.fws.gov/birds/',
                               timestamp=True)


@ia_vcr.use_cassette()
def test_get_memento_with_requires_datetime_with_regular_url():
    with WaybackClient() as client:
        with pytest.raises(TypeError):
            client.get_memento('https://www.fws.gov/birds/')


@ia_vcr.use_cassette()
def test_get_memento_with_archive_url():
    with WaybackClient() as client:
        memento = client.get_memento(
            'https://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/')

        # Metadata About the Memento
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode
        assert 'https://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/' == memento.memento_url
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
                           'https://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/',
                           'https://web.archive.org/web/20171124151315/https://www.fws.gov/birds/')
        memento = client.get_memento(record)
        assert 'https://www.fws.gov/birds/' == memento.url
        assert datetime(2017, 11, 24, 15, 13, 15, tzinfo=timezone.utc) == memento.timestamp
        assert 'id_' == memento.mode


@ia_vcr.use_cassette()
def test_get_memento_with_mode():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     timestamp=datetime(2017, 11, 24, 15, 13, 15),
                                     mode=Mode.view)
        assert '' == memento.mode
        assert ('https://web.archive.org/web/20171124151315/https://www.fws.gov/birds/'
                == memento.memento_url)
        assert ('https://web.archive.org/web/20171124151315/https://www.fws.gov/birds/'
                == memento.links['memento']['url'])
        assert ('https://web.archive.org/web/20050323155300/http://www.fws.gov:80/birds'
                == memento.links['first memento']['url'])

        memento = client.get_memento('https://www.fws.gov/birds/',
                                     timestamp=datetime(2017, 11, 24, 15, 13, 15))
        assert 'id_' == memento.mode
        assert ('https://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/'
                == memento.memento_url)
        assert ('https://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/'
                == memento.links['memento']['url'])
        assert ('https://web.archive.org/web/20050323155300id_/http://www.fws.gov:80/birds'
                == memento.links['first memento']['url'])


@ia_vcr.use_cassette()
def test_get_memento_with_mode_string():
    with WaybackClient() as client:
        memento = client.get_memento('https://www.fws.gov/birds/',
                                     timestamp=datetime(2017, 11, 24, 15, 13, 15),
                                     mode='id_')
        assert 'id_' == memento.mode
        assert 'https://web.archive.org/web/20171124151315id_/https://www.fws.gov/birds/' == memento.memento_url


@ia_vcr.use_cassette()
def test_get_memento_with_mode_boolean_is_not_allowed():
    with WaybackClient() as client:
        with pytest.raises(TypeError):
            client.get_memento('https://www.fws.gov/birds/',
                               timestamp=datetime(2017, 11, 24, 15, 13, 15),
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
            'https://web.archive.org/web/20180808094144id_/https://www.epa.gov/ghgreporting/san5779-factsheet')
        assert len(memento.history) == 1        # memento redirects
        assert len(memento.debug_history) == 2  # actual HTTP redirects


@ia_vcr.use_cassette()
def test_get_memento_with_path_based_redirects():
    """
    Most redirects in Wayback redirect to a complete URL, with headers like:
        Location: https://web.archive.org/web/20201027215555id_/https://www.whitehouse.gov/administration
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
        Location: https://web.archive.org/web/20201027215555id_/https://www.whitehouse.gov/administration
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
def test_get_memento_with_redirect_in_view_mode():
    """
    Redirects in view mode respond with different headers, status codes, and
    bodies that other modes. They require special handling and testing.
    """
    with WaybackClient() as client:
        memento = client.get_memento(
            'https://www.whitehouse.gov/administration/eop/ostp/about/student/faqs',
            timestamp='20201027215555',
            mode=Mode.view)
        assert len(memento.history) == 1        # memento redirects
        assert len(memento.debug_history) == 2  # actual HTTP redirects


@ia_vcr.use_cassette()
def test_get_memento_should_fail_for_non_playbackable_mementos():
    with WaybackClient() as client:
        with pytest.raises(MementoPlaybackError):
            client.get_memento('https://www.fws.gov/birds/', '20150509080314')


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
        # https://web.archive.org/web/20200201020357id_/http://epa.gov/climatechange
        #   Is not a memento, and sends us to:
        #   https://web.archive.org/web/20200201023757id_/https://www.epa.gov/climatechange
        #     Which is a memento of a redirect to:
        #     https://web.archive.org/web/20200201023757id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        #       ...which is not a memento, and redirects to:
        #       https://web.archive.org/web/20200201024405id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        start_url = ('https://web.archive.org/web/20200201020357id_/'
                     'http://epa.gov/climatechange')
        target = ('https://web.archive.org/web/20200201024405id_/'
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
        # https://web.archive.org/web/20200201020357id_/http://epa.gov/climatechange
        #   Is not a memento, and sends us to:
        #   https://web.archive.org/web/20200201023757id_/https://www.epa.gov/climatechange
        #     Which is a memento of a redirect. Because follow_redirects=False,
        #     we should *not* follow it to:
        #     https://web.archive.org/web/20200201023757id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        #       ...and then to:
        #       https://web.archive.org/web/20200201024405id_/https://www.epa.gov/sites/production/files/signpost/cc.html
        start_url = ('https://web.archive.org/web/20200201020357id_/'
                     'http://epa.gov/climatechange')
        target = ('https://web.archive.org/web/20200201023757id_/'
                  'https://www.epa.gov/climatechange')
        memento = client.get_memento(start_url, exact=False, follow_redirects=False)
        assert 'https://www.epa.gov/climatechange' == memento.url
        assert target == memento.memento_url
        assert memento.status_code == 301
        assert 'https://www.epa.gov/sites/production/files/signpost/cc.html' == memento.headers['Location']
        assert len(memento.history) == 0
        assert len(memento.debug_history) == 1


@ia_vcr.use_cassette()
def test_get_memento_returns_memento_with_accurate_url():
    with WaybackClient() as client:
        # This memento is actually captured from 'https://www.', not 'http://'.
        memento = client.get_memento('http://fws.gov/',
                                     timestamp='20171124143728')
        assert memento.url == 'https://www.fws.gov/'


def return_timeout(self, *args, **kwargs) -> HTTPResponse:
    """
    Patch urllib3.HTTPConnectionPool.urlopen with this in order to return a
    response with the provided timeout value as the response body.

    Usage:
    >>> @mock.patch('urllib3.HTTPConnectionPool.urlopen', side_effect=return_timeout)
    >>> def test_timeout(self, mock_class):
    >>>    assert urllib3.get('http://test.com', timeout=5).data == b'5'
    """
    res = HTTPResponse(
        body=str(kwargs.get('timeout', None)).encode(),
        headers=HTTPHeaderDict(),
        status=200
    )
    return res


class TestWaybackSession:
    def test_request_retries(self, urllib3_mock):
        urllib3_mock.get('http://test.com', [{'text': 'bad1', 'status_code': 503},
                                             {'text': 'bad2', 'status_code': 503},
                                             {'text': 'good', 'status_code': 200}])
        session = WaybackSession(retries=2, backoff=0.1)
        response = session.request('GET', 'http://test.com')
        assert response.is_success

        session.close()

    def test_stops_after_given_retries(self, urllib3_mock):
        urllib3_mock.get('http://test.com', [{'text': 'bad1', 'status_code': 503},
                                             {'text': 'bad2', 'status_code': 503},
                                             {'text': 'good', 'status_code': 200}])
        session = WaybackSession(retries=1, backoff=0.1)
        response = session.request('GET', 'http://test.com')
        assert response.status_code == 503
        assert response.text == 'bad2'

    def test_only_retries_some_errors(self, urllib3_mock):
        urllib3_mock.get('http://test.com', [{'text': 'bad1', 'status_code': 400},
                                             {'text': 'good', 'status_code': 200}])
        session = WaybackSession(retries=1, backoff=0.1)
        response = session.request('GET', 'http://test.com')
        assert response.status_code == 400

    def test_raises_rate_limit_error(self, urllib3_mock):
        urllib3_mock.get('http://test.com', [WAYBACK_RATE_LIMIT_ERROR])
        with pytest.raises(RateLimitError):
            session = WaybackSession(retries=0)
            session.request('GET', 'http://test.com')

    def test_rate_limit_error_includes_retry_after(self, urllib3_mock):
        urllib3_mock.get('http://test.com', [WAYBACK_RATE_LIMIT_ERROR])
        with pytest.raises(RateLimitError) as excinfo:
            session = WaybackSession(retries=0)
            session.request('GET', 'http://test.com')

        assert excinfo.value.retry_after == 10

    @mock.patch('urllib3.HTTPConnectionPool.urlopen', side_effect=return_timeout)
    def test_timeout_applied_session(self, mock_class):
        # Is the timeout applied through the WaybackSession
        session = WaybackSession(timeout=1)
        res = session.request('GET', 'http://test.com')
        assert res.text == str(Urllib3Timeout(connect=1, read=1))
        # Overwriting the default in the requests method
        res = session.request('GET', 'http://test.com', timeout=None)
        assert res.text == str(Urllib3Timeout(connect=None, read=None))
        res = session.request('GET', 'http://test.com', timeout=2)
        assert res.text == str(Urllib3Timeout(connect=2, read=2))

    # XXX: We should probably change this test. What we really want to test is
    # that the default when unspecified in both the session and the request
    # is not None.
    @mock.patch('urllib3.HTTPConnectionPool.urlopen', side_effect=return_timeout)
    def test_timeout_applied_request(self, mock_class):
        # Using the default value
        session = WaybackSession()
        res = session.request('GET', 'http://test.com')
        assert res.text == str(Urllib3Timeout(connect=60, read=60))
        # Overwriting the default
        res = session.request('GET', 'http://test.com', timeout=None)
        assert res.text == str(Urllib3Timeout(connect=None, read=None))
        res = session.request('GET', 'http://test.com', timeout=2)
        assert res.text == str(Urllib3Timeout(connect=2, read=2))

    @mock.patch('urllib3.HTTPConnectionPool.urlopen', side_effect=return_timeout)
    def test_timeout_empty(self, mock_class):
        # Disabling default timeout
        session = WaybackSession(timeout=None)
        res = session.request('GET', 'http://test.com')
        assert res.text == str(Urllib3Timeout(connect=None, read=None))
        # Overwriting the default
        res = session.request('GET', 'http://test.com', timeout=1)
        assert res.text == str(Urllib3Timeout(connect=1, read=1))

    @ia_vcr.use_cassette()
    def test_search_rate_limits(self):
        # The timing relies on the cassettes being present,
        # therefore the first run might fail.
        # Since another test might run before this one,
        # I have to wait one second before starting.
        time.sleep(1)
        # First test that the default rate limits are correctly applied.
        start_time = time.time()
        with WaybackClient() as client:
            for i in range(3):
                next(client.search('zew.de'))
        duration_with_limits = time.time() - start_time

        # Check that disabling the rate limits through the search API works.
        start_time = time.time()
        with WaybackClient(WaybackSession(search_calls_per_second=0)) as client:
            for i in range(3):
                next(client.search('zew.de'))
        duration_without_limits = time.time() - start_time

        # Check that a different rate limit set through the session is applied correctly.
        # I need to sleep one half second in order to reset the rate limit.
        time.sleep(0.5)
        start_time = time.time()
        with WaybackClient(WaybackSession(search_calls_per_second=2)) as client:
            for i in range(3):
                next(client.search('zew.de'))
        duration_with_limits_custom = time.time() - start_time

        assert 2.4 <= duration_with_limits <= 2.6
        assert 0.0 <= duration_without_limits <= 0.05
        assert 0.0 <= duration_with_limits_custom <= 1.05

    @ia_vcr.use_cassette()
    def test_memento_rate_limits(self):
        # The timing relies on the cassettes being present,
        # therefore the first run might fail.
        # Since another test might run before this one,
        # I have to wait one call before starting.
        time.sleep(1/30)
        with WaybackClient() as client:
            cdx = next(client.search('zew.de'))
        # First test that the default rate limits are correctly applied.
        start_time = time.time()
        with WaybackClient() as client:
            for i in range(11):
                client.get_memento(cdx)
        duration_with_limits = time.time() - start_time

        # Check that disabling the rate limits through the get_memento API works.
        time.sleep(1)  # Wait to exceed any previous rate limits.
        start_time = time.time()
        with WaybackClient(WaybackSession(memento_calls_per_second=0)) as client:
            for i in range(3):
                client.get_memento(cdx)
        duration_without_limits = time.time() - start_time

        # Check that a different rate limit set through the session is applied correctly.
        time.sleep(1)  # Wait to exceed any previous rate limits.
        start_time = time.time()
        with WaybackClient(WaybackSession(memento_calls_per_second=10)) as client:
            for i in range(6):
                client.get_memento(cdx)
        duration_with_limits_custom = time.time() - start_time

        assert 1.15 <= duration_with_limits <= 1.35
        assert 0.0 <= duration_without_limits <= 0.05
        assert 0.5 <= duration_with_limits_custom <= 0.55
