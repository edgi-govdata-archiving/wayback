import json
import os
import tempfile
from tornado.testing import AsyncHTTPTestCase
import web_monitoring.diffing_server as df


class DiffingServerTestCase(AsyncHTTPTestCase):

    def get_app(self):
        return df.make_app()

    def json_check(self, response):
        json_header = response.headers.get('Content-Type').split(';')
        self.assertEqual(json_header[0], 'application/json')

        json_response = json.loads(response.body)
        self.assertTrue(isinstance(json_response['code'], int))
        self.assertTrue(isinstance(json_response['error'], str))

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
