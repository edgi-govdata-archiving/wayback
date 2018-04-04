from datetime import datetime
import requests_mock
from web_monitoring.utils import extract_title, retryable_request, rate_limited


def test_extract_title():
    title = extract_title(b'''<html>
        <head><title>THIS IS THE TITLE</title></head>
        <body>Blah</body>
    </html>''')
    assert title == 'THIS IS THE TITLE'


def test_extract_title_from_titleless_page():
    title = extract_title(b'''<html>
        <head><meta charset="utf-8"></head>
        <body>Blah</body>
    </html>''')
    assert title == ''


def test_rate_limited():
    start_time = datetime.utcnow()
    for i in range(2):
        with rate_limited(calls_per_second=2):
            1 + 1
    duration = datetime.utcnow() - start_time
    assert duration.total_seconds() > 0.5


def test_separate_rate_limited_groups_do_not_affect_each_other():
    start_time = datetime.utcnow()

    with rate_limited(calls_per_second=2, group='a'):
        1 + 1
    with rate_limited(calls_per_second=2, group='b'):
        1 + 1
    with rate_limited(calls_per_second=2, group='a'):
        1 + 1
    with rate_limited(calls_per_second=2, group='b'):
        1 + 1

    duration = datetime.utcnow() - start_time
    assert duration.total_seconds() > 0.5
    assert duration.total_seconds() < 0.55


def test_retryable_request_retries():
    with requests_mock.Mocker() as mock:
        mock.get('http://test.com', [{'text': 'bad', 'status_code': 503},
                                     {'text': 'good', 'status_code': 200}])
        response = retryable_request('GET', 'http://test.com', backoff=0)
        assert response.ok


def test_retryable_request_stops_after_given_retries():
    with requests_mock.Mocker() as mock:
        mock.get('http://test.com', [{'text': 'bad1', 'status_code': 503},
                                     {'text': 'bad2', 'status_code': 503},
                                     {'text': 'bad3', 'status_code': 503},
                                     {'text': 'good', 'status_code': 200}])
        response = retryable_request('GET', 'http://test.com', retries=2, backoff=0)
        assert response.status_code == 503
        assert response.text == 'bad3'


def test_retryable_request_only_retries_gateway_errors():
    with requests_mock.Mocker() as mock:
        mock.get('http://test.com', [{'text': 'bad1', 'status_code': 400},
                                     {'text': 'good', 'status_code': 200}])
        response = retryable_request('GET', 'http://test.com', backoff=0)
        assert response.status_code == 400


def test_retryable_request_with_custom_retry_logic():
    with requests_mock.Mocker() as mock:
        mock.get('http://test.com', [{'text': 'bad1', 'status_code': 400},
                                     {'text': 'good', 'status_code': 200}])

        response = retryable_request('GET', 'http://test.com', backoff=0,
                                     should_retry=lambda r: r.status_code == 400)
        assert response.status_code == 200
