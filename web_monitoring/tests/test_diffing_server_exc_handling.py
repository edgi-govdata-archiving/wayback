from tornado.testing import AsyncHTTPTestCase
import web_monitoring.diffing_server as df
from web_monitoring.diff_errors import UndecodableContentError

class DiffingServerExceptionHandlingTest(AsyncHTTPTestCase):

    def get_app(self):
        app = df.make_app()
        app.listen(str(self.get_http_port()))
        return

    def test_invalid_url_a_format(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/html_token?format=json&include=all&a=example.org&b=https://example.org')
        self.assertEqual(response.code, 400)

    def test_invalid_url_b_format(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/html_token?format=json&include=all&a=https://example.org&b=example.org')
        self.assertEqual(response.code, 400)

    def test_invalid_diffing_method(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/non_existing?format=json&include=all&a=example.org&b=https://example.org')
        self.assertEqual(response.code, 404)
    
    def test_missing_url_a(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/html_token?format=json&include=all&b=https://example.org')
        self.assertEqual(response.code, 400)

    def test_missing_url_b(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/html_token?format=json&include=all&a=https://example.org')
        self.assertEqual(response.code, 400)

    def test_not_reachable_url_a(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/html_token?format=json&include=all&a=https://eeexample.org&b=https://example.org')
        self.assertEqual(response.code, 400)

    def test_not_reachable_url_b(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/html_token?format=json&include=all&a=https://example.org&b=https://eeexample.org')
        self.assertEqual(response.code, 400)

    def test_missing_params_caller_func(self):
        response = self.fetch('http://example.org/')
        with self.assertRaises(KeyError):  
            df.caller(mockDiffingMethod, response, response)

    def test_undecodable_content(self):
        response = self.fetch('https://www.cl.cam.ac.uk/~mgk25/ucs/examples/UTF-8-test.txt')
        with self.assertRaises(UndecodableContentError):
            df._decode_body(response,'a',False)

    def test_fetch_undecodable_content(self):
        port = self.get_http_port()
        response = self.fetch(f'http://localhost:{port}/html_token?format=json&include=all&a=https://example.org&b=https://www.cl.cam.ac.uk/~mgk25/ucs/examples/UTF-8-test.txt')
        self.assertEqual(response.code, 422)

def mock_diffing_method(c_body):
        return

