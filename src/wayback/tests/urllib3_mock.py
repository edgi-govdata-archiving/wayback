"""
This module provides really simplistic mocking support for urllib3. It
mirrors the parts of `requests-mock` that we currently use, and no more.

There is an existing urllib3_mock project, but it has not been maintained for
many years and no longer works correctly with current versions of urllib3:
https://pypi.org/project/urllib3-mock/
"""

from io import BytesIO
from urllib.parse import urlparse, ParseResult, parse_qs
import pytest
from urllib3 import HTTPConnectionPool, HTTPResponse
# The Header dict lives in a different place for urllib3 v2:
try:
    from urllib3 import HTTPHeaderDict
# vs. urllib3 v1:
except ImportError:
    from urllib3.response import HTTPHeaderDict


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
