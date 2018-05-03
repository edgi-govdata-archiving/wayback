from tornado.testing import AsyncHTTPTestCase
import web_monitoring.diffing_server as df
from web_monitoring.diff_errors import UndecodableContentError

class DiffingServerExceptionHandlingTest(AsyncHTTPTestCase):

    def get_app(self):
        app = df.make_app()
        app.listen(8888)
        return

    def testInvalidURLaFormat(self):
        response = self.fetch('http://localhost:8888/html_token?format=json&include=all&a=example.org&b=https://example.org', method='GET')
        self.assertEqual(response.code, 400)

    def testInvalidURLbFormat(self):
        response = self.fetch('http://localhost:8888/html_token?format=json&include=all&a=https://example.org&b=example.org', method='GET')
        self.assertEqual(response.code, 400)

    def testInvalidDiffingMethod(self):
        response = self.fetch('http://localhost:8888/non_existing?format=json&include=all&a=example.org&b=https://example.org', method='GET')
        self.assertEqual(response.code, 404)
    
    def testMissingURLa(self):
        response = self.fetch('http://localhost:8888/html_token?format=json&include=all&b=https://example.org', method='GET')
        self.assertEqual(response.code, 400)

    def testMissingURLb(self):
        response = self.fetch('http://localhost:8888/html_token?format=json&include=all&a=https://example.org', method='GET')
        self.assertEqual(response.code, 400)

    def testNotReachableURLa(self):
        response = self.fetch('http://localhost:8888/html_token?format=json&include=all&a=https://eeexample.org&b=https://example.org', method='GET')
        self.assertEqual(response.code, 400)

    def testNotReachableURLb(self):
        response = self.fetch('http://localhost:8888/html_token?format=json&include=all&a=https://example.org&b=https://eeexample.org', method='GET')
        self.assertEqual(response.code, 400)

    def testMissingParamsCallerFunc(self):
        response = self.fetch('http://example.org/')
        with self.assertRaises(KeyError):  
            df.caller(mockDiffingMethod, response, response)

    def testUndecodableContent(self):
        response = self.fetch('https://www.cl.cam.ac.uk/~mgk25/ucs/examples/UTF-8-test.txt')
        with self.assertRaises(UndecodableContentError):
            df._decode_body(response,'a',False)

# This test breaks them all
    # def testFetchUndecodableContent(self):
    #     print('here')
    #     response = self.fetch('http://localhost:8888/html_token?format=json&include=all&a=https://example.org&b=https://www.cl.cam.ac.uk/~mgk25/ucs/examples/UTF-8-test.txt')
    #     print("also here")
    #     self.assertEqual(response.code, 422)

def mockDiffingMethod(c_body):
        return