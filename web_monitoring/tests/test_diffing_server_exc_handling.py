import json
import os
import re
import tempfile
from tornado.testing import AsyncHTTPTestCase
from unittest.mock import patch
import web_monitoring.diffing_server as df
import web_monitoring
from tornado.escape import utf8
from tornado.httpclient import HTTPResponse, AsyncHTTPClient
from tornado.httputil import HTTPHeaders
from io import BytesIO


class DiffingServerTestCase(AsyncHTTPTestCase):

    def get_app(self):
        return df.make_app()

    def json_check(self, response):
        json_header = response.headers.get('Content-Type').split(';')
        self.assertEqual(json_header[0], 'application/json')

        json_response = json.loads(response.body)
        self.assertTrue(isinstance(json_response['code'], int))
        self.assertTrue(isinstance(json_response['error'], str))


class DiffingServerIndexTest(DiffingServerTestCase):
    def test_version(self):
        response = self.fetch('/')
        json_response = json.loads(response.body)
        assert json_response['version'] == web_monitoring.__version__


class DiffingServerLocalHandlingTest(DiffingServerTestCase):

    def test_one_local(self):
        with tempfile.NamedTemporaryFile() as a:
            response = self.fetch('/identical_bytes?'
                                  f'a=file://{a.name}&b=https://example.org')
            self.assertEqual(response.code, 200)

    def test_both_local(self):
        with tempfile.NamedTemporaryFile() as a:
            with tempfile.NamedTemporaryFile() as b:
                response = self.fetch('/identical_bytes?'
                                      f'a=file://{a.name}&b=file://{b.name}')
                self.assertEqual(response.code, 200)


class DiffingServerHealthCheckHandlingTest(DiffingServerTestCase):

    def test_healthcheck(self):
        response = self.fetch('/healthcheck')
        self.assertEqual(response.code, 200)


class DiffingServerFetchTest(DiffingServerTestCase):

    def test_pass_headers(self):
        mock = MockAsyncHttpClient()
        with patch.object(df, 'client', wraps=mock):
            mock.respond_to(r'/a$')
            mock.respond_to(r'/b$')

            self.fetch('/html_source_dmp?'
                       'pass_headers=Authorization,%20User-Agent&'
                       'a=https://example.org/a&b=https://example.org/b',
                       headers={'User-Agent': 'Some Agent',
                                'Authorization': 'Bearer xyz',
                                'Accept': 'application/json'})

            a_headers = mock.requests['https://example.org/a'].headers
            assert a_headers.get('User-Agent') == 'Some Agent'
            assert a_headers.get('Authorization') == 'Bearer xyz'
            assert a_headers.get('Accept') != 'application/json'

            b_headers = mock.requests['https://example.org/b'].headers
            assert b_headers.get('User-Agent') == 'Some Agent'
            assert b_headers.get('Authorization') == 'Bearer xyz'
            assert b_headers.get('Accept') != 'application/json'


class DiffingServerExceptionHandlingTest(DiffingServerTestCase):

    def test_local_file_disallowed_in_production(self):
        original = os.environ.get('WEB_MONITORING_APP_ENV')
        os.environ['WEB_MONITORING_APP_ENV'] = 'production'
        try:
            with tempfile.NamedTemporaryFile() as a:
                response = self.fetch('/identical_bytes?'
                                      f'a=file://{a.name}&b=https://example.org')
                self.assertEqual(response.code, 403)
        finally:
            if original is None:
                del os.environ['WEB_MONITORING_APP_ENV']
            else:
                os.environ['WEB_MONITORING_APP_ENV'] = original

    def test_invalid_url_a_format(self):
        response = self.fetch('/html_token?format=json&include=all&'
                              'a=example.org&b=https://example.org')
        self.json_check(response)
        self.assertEqual(response.code, 400)

    def test_invalid_url_b_format(self):
        response = self.fetch('/html_token?format=json&include=all&'
                              'a=https://example.org&b=example.org')
        self.json_check(response)
        self.assertEqual(response.code, 400)

    def test_invalid_diffing_method(self):
        response = self.fetch('/non_existing?format=json&include=all&'
                              'a=example.org&b=https://example.org')
        self.json_check(response)
        self.assertEqual(response.code, 404)

    def test_missing_url_a(self):
        response = self.fetch('/html_token?format=json&include=all&'
                              'b=https://example.org')
        self.json_check(response)
        self.assertEqual(response.code, 400)

    def test_missing_url_b(self):
        response = self.fetch('/html_token?format=json&include=all&'
                              'a=https://example.org')
        self.json_check(response)
        self.assertEqual(response.code, 400)

    def test_not_reachable_url_a(self):
        response = self.fetch('/html_token?format=json&include=all&'
                              'a=https://eeexample.org&b=https://example.org')
        self.json_check(response)
        self.assertEqual(response.code, 400)

    def test_not_reachable_url_b(self):
        response = self.fetch('/html_token?format=json&include=all&'
                              'a=https://example.org&b=https://eeexample.org')
        self.json_check(response)
        self.assertEqual(response.code, 400)

    def test_missing_params_caller_func(self):
        response = self.fetch('http://example.org/')
        with self.assertRaises(KeyError):
            df.caller(mock_diffing_method, response, response)

    def test_a_is_404(self):
        response = self.fetch('/html_token?format=json&include=all'
                              '&a=http://httpstat.us/404'
                              '&b=https://example.org')
        self.assertEqual(response.code, 404)
        self.json_check(response)


def mock_diffing_method(c_body):
    return


# TODO: we may want to extract this to a support module
class MockAsyncHttpClient(AsyncHTTPClient):
    """
    A mock Tornado AsyncHTTPClient. Use it to set fake responses and track
    requests made with an AsyncHTTPClient instance.
    """

    def __init__(self):
        self.requests = {}
        self.stub_responses = []

    def respond_to(self, matcher, code=200, body='', headers={}, **kwargs):
        """
        Set up a fake HTTP response. If a request is made and no fake response
        set up with `respond_to()` matches it, an error will be raised.

        Parameters
        ----------
        matcher : callable or string
            Defines whether this response data should be used for a given
            request. If callable, it will be called with the Tornado Request
            object and should return `True` if the response should be used. If
            a string, it will be used as a regular expression to match the
            request URL.
        code : int, optional
            The HTTP response code to response with. Defaults to 200 (OK).
        body : string, optional
            The response body to send back.
        headers : dict, optional
            Any headers to use for the response.
        **kwargs : any, optional
            Additional keyword args to pass to the Tornado Response.
            Reference: http://www.tornadoweb.org/en/stable/httpclient.html#tornado.httpclient.HTTPResponse
        """
        if isinstance(matcher, str):
            regex = re.compile(matcher)
            matcher = lambda request: regex.search(request.url) is not None

        if 'Content-Type' not in headers and 'content-type' not in headers:
            headers['Content-Type'] = 'text/plain'

        self.stub_responses.append({
            'matcher': matcher,
            'code': code,
            'body': body,
            'headers': headers,
            'extra': kwargs
        })

    def fetch_impl(self, request, callback):
        stub = self._find_stub(request)
        buffer = BytesIO(utf8(stub['body']))
        headers = HTTPHeaders(stub['headers'])
        response = HTTPResponse(request, stub['code'], buffer=buffer,
                                headers=headers, **stub['extra'])
        self.requests[request.url] = request
        callback(response)

    def _find_stub(self, request):
        for stub in self.stub_responses:
            if stub['matcher'](request):
                return stub
        raise ValueError(f'No response stub for {request.url}')
