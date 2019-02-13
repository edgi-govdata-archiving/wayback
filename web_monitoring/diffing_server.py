import concurrent.futures
from docopt import docopt
import hashlib
import inspect
import functools
import os
import re
import sentry_sdk
import tornado.gen
import tornado.httpclient
import tornado.ioloop
import tornado.web
import traceback
import web_monitoring
import web_monitoring.differs
from web_monitoring.diff_errors import UndiffableContentError, UndecodableContentError
import web_monitoring.html_diff_render
import web_monitoring.links_diff

# Track errors with Sentry.io. It will automatically detect the `SENTRY_DSN`
# environment variable. If not set, all its methods will operate conveniently
# as no-ops.
sentry_sdk.init(ignore_errors=[KeyboardInterrupt])
# Tornado logs any non-success response at ERROR level, which Sentry captures
# by default. We don't really want those logs.
sentry_sdk.integrations.logging.ignore_logger('tornado.access')

DIFFER_PARALLELISM = os.environ.get('DIFFER_PARALLELISM', 10)

# Map tokens in the REST API to functions in modules.
# The modules do not have to be part of the web_monitoring package.
DIFF_ROUTES = {
    "length": web_monitoring.differs.compare_length,
    "identical_bytes": web_monitoring.differs.identical_bytes,
    "pagefreezer": web_monitoring.differs.pagefreezer,
    "side_by_side_text": web_monitoring.differs.side_by_side_text,
    "links": web_monitoring.links_diff.links_diff_html,
    "links_json": web_monitoring.links_diff.links_diff_json,
    # applying diff-match-patch (dmp) to strings (no tokenization)
    "html_text_dmp": web_monitoring.differs.html_text_diff,
    "html_source_dmp": web_monitoring.differs.html_source_diff,
    # three different approaches to the same goal:
    "html_token": web_monitoring.html_diff_render.html_diff_render,
    "html_tree": web_monitoring.differs.html_tree_diff,
    "html_perma_cc": web_monitoring.differs.html_differ,

    # deprecated synonyms
    "links_diff": web_monitoring.links_diff.links_diff,
    "html_text_diff": web_monitoring.differs.html_text_diff,
    "html_source_diff": web_monitoring.differs.html_source_diff,
    "html_visual_diff": web_monitoring.html_diff_render.html_diff_render,
    "html_tree_diff": web_monitoring.differs.html_tree_diff,
    "html_differ": web_monitoring.differs.html_differ,
}

# Matches a <meta> tag in HTML used to specify the character encoding:
# <meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
# <meta charset="utf-8" />
META_TAG_PATTERN = re.compile(
    b'<meta[^>]+charset\\s*=\\s*[\'"]?([^>]*?)[ /;\'">]',
    re.IGNORECASE)

# Matches an XML prolog that specifies character encoding:
# <?xml version="1.0" encoding="ISO-8859-1"?>
XML_PROLOG_PATTERN = re.compile(
    b'<?xml\\s[^>]*encoding=[\'"]([^\'"]+)[\'"].*\?>',
    re.IGNORECASE)

client = tornado.httpclient.AsyncHTTPClient()


class MockRequest:
    "An HTTPRequest-like object for local file:/// requests."
    def __init__(self, url):
        self.url = url

class MockResponse:
    "An HTTPResponse-like object for local file:/// requests."
    def __init__(self, url, body, headers):
        self.request = MockRequest(url)
        self.body = body
        self.headers = headers
        self.error = None

DEBUG_MODE = os.environ.get('DIFFING_SERVER_DEBUG', 'False').strip().lower() == 'true'

VALIDATE_TARGET_CERTIFICATES = \
    os.environ.get('VALIDATE_TARGET_CERTIFICATES', 'False').strip().lower() == 'true'

access_control_allow_origin_header = \
    os.environ.get('ACCESS_CONTROL_ALLOW_ORIGIN_HEADER')

class BaseHandler(tornado.web.RequestHandler):

    def set_default_headers(self):
        if access_control_allow_origin_header is not None:
            if 'allowed_origins' not in self.settings:
                self.settings['allowed_origins'] = \
                    set([origin.strip() for origin
                         in access_control_allow_origin_header.split(',')])
            req_origin = self.request.headers.get('Origin')
            if req_origin:
                allowed = self.settings.get('allowed_origins')
                if allowed and (req_origin in allowed or '*' in allowed):
                    self.set_header('Access-Control-Allow-Origin', req_origin)
            self.set_header('Access-Control-Allow-Credentials', 'true')
            self.set_header('Access-Control-Allow-Headers', 'x-requested-with')
            self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

    def options(self):
        # no body
        self.set_status(204)
        self.finish()


class DiffHandler(BaseHandler):
    # subclass must define `differs` attribute

    # If query parameters repeat, take last one.
    # Decode clean query parameters into unicode strings and cache the results.
    @functools.lru_cache()
    def decode_query_params(self):
        query_params = {k: v[-1].decode() for k, v in
                        self.request.arguments.items()}
        return query_params

    # Compute our own ETag header values.
    def compute_etag(self):
        # We're not actually hashing content for this, since that is expensive.
        validation_bytes = str(
            web_monitoring.__version__
            + self.request.path
            + str(self.decode_query_params())
        ).encode('utf-8')

        # Uses the "weak validation" directive since we don't guarantee that future
        # responses for the same diff will be byte-for-byte identical.
        etag = str('W/"' + web_monitoring.utils.hash_content(validation_bytes) + '"').encode('utf-8')
        return etag

    def head(self, differ):

        self.set_etag_header()
        if self.check_etag_header():
            self.set_status(304)
            self.finish()
            return


    @tornado.gen.coroutine
    def get(self, differ):

        # Skip a whole bunch of work if possible.
        self.set_etag_header()
        if self.check_etag_header():
            self.set_status(304)
            self.finish()
            return

        # Find the diffing function registered with the name given by `differ`.
        try:
            func = self.differs[differ]
        except KeyError:
            self.send_error(404,
                            reason=f'Unknown diffing method: `{differ}`. '
                                   f'You can get a list of '
                                   f'supported differs from '
                                   f'the `/` endpoint.')
            return

        query_params = self.decode_query_params()
        # The logic here is a bit tortured in order to allow one or both URLs
        # to be local files, while still optimizing the common case of two
        # remote URLs that we want to fetch in parallel.
        try:
            urls = {param: query_params.pop(param) for param in ('a', 'b')}
        except KeyError:
            self.send_error(
                400,
                reason='Malformed request. '
                       'You must provide a URL as the value '
                       'for both `a` and `b` query parameters.')
            return
        # Special case for local files, for dev/testing.
        responses = {}
        for param, url in urls.items():
            if url.startswith('file://'):
                if os.environ.get('WEB_MONITORING_APP_ENV') == 'production':
                    self.send_error(
                        403, reason=("Local files cannot be used in "
                                     "production environment."))
                    return
                headers = {'Content-Type': 'application/html; charset=UTF-8'}
                with open(url[7:], 'rb') as f:
                    body = f.read()
                    responses[param] = MockResponse(url, body, headers)
        # Now fetch any nonlocal URLs.
        # Pass request headers defined by URL param pass_headers=HEADER_NAME
        # to nonlocal URLs. Useful for passing data like cookie headers.
        # HEADER_NAME can be one or multiple headers separated by ','
        to_fetch = {k: v for k, v in urls.items() if k not in responses}
        headers = {}
        header_keys = query_params.get('pass_headers')
        if header_keys:
            for header_key in header_keys.split(','):
                header_key = header_key.strip()
                header_value = self.request.headers.get(header_key)
                if header_value:
                    headers[header_key] = header_value

        fetched = yield [client.fetch(url, headers=headers, raise_error=False,
                                      validate_cert=VALIDATE_TARGET_CERTIFICATES)
                         for url in to_fetch.values()]
        responses.update({param: response for param, response in
                          zip(to_fetch, fetched)})

        try:
            for response in responses.values():
                self.check_response_for_error(response)
        except tornado.httpclient.HTTPError:
            return

        # Validate response bytes against hash, if provided.
        for param, response in responses.items():
            try:
                expected_hash = query_params.pop(f'{param}_hash')
            except KeyError:
                # No hash provided in the request. Skip validation.
                pass
            else:
                actual_hash = hashlib.sha256(response.body).hexdigest()
                if actual_hash != expected_hash:
                    self.send_error(
                        500, reason='Fetched content does not match hash.')
                    return

        # TODO: Add caching of fetched URIs.

        # Pass the bytes and any remaining args to the diffing function.
        res = yield self.diff(func, responses['a'], responses['b'],
                              query_params)
        res['version'] = web_monitoring.__version__
        # Echo the client's request unless the differ func has specified
        # somethine else.
        res.setdefault('type', differ)
        self.write(res)

    @tornado.gen.coroutine
    def diff(self, func, a, b, params, tries=2):
        """
        Actually do a diff between two pieces of content, optionally retrying
        if the process pool that executes the diff breaks.
        """
        executor = self.get_diff_executor()
        for attempt in range(tries):
            try:
                result = yield executor.submit(caller, func, a, b, **params)
                raise tornado.gen.Return(result)
            except concurrent.futures.process.BrokenProcessPool:
                executor = self.get_diff_executor(reset=True)

    # NOTE: this doesn't do anything async, but if we change it to do so, we
    # need to add a lock (either asyncio.Lock or tornado.locks.Lock).
    def get_diff_executor(self, reset=False):
        executor = self.settings.get('diff_executor')
        if reset or not executor:
            if executor:
                try:
                    executor.shutdown(wait=False)
                except Exception:
                    pass
            executor = concurrent.futures.ProcessPoolExecutor(
                DIFFER_PARALLELISM)
            self.settings['diff_executor'] = executor

        return executor

    def write_error(self, status_code, **kwargs):
        response = {'code': status_code, 'error': self._reason}

        # Handle errors that are allowed to be public
        # TODO: this error filtering should probably be in `send_error()`
        actual_error = 'exc_info' in kwargs and kwargs['exc_info'][1] or None
        if isinstance(actual_error, (UndiffableContentError, UndecodableContentError)):
            response['code'] = 422
            response['error'] = str(actual_error)

        # Pass non-raised (i.e. we manually called `send_error()`), non-user
        # errors to Sentry.io.
        if actual_error is None and response['code'] >= 500:
            # TODO: this breadcrumb should happen at the start of the request
            # handler, but we need to test and make sure crumbs are properly
            # attached to *this* HTTP request and don't bleed over to others,
            # since Sentry's special support for Tornado has been dropped.
            headers = dict(self.request.headers)
            if 'Authorization' in headers:
                headers['Authorization'] = '[removed]'
            sentry_sdk.add_breadcrumb(category='request', data={
                'url': self.request.full_url(),
                'method': self.request.method,
                'headers': headers,
            })
            sentry_sdk.capture_message(f'{self._reason} (status: {response["code"]})')

        # Fill in full info if configured to do so
        if self.settings.get('serve_traceback') and 'exc_info' in kwargs:
            response['error'] = str(kwargs['exc_info'][1])
            stack_lines = traceback.format_exception(*kwargs['exc_info'])
            response['stack'] = ''.join(stack_lines)

        if response['code'] != status_code:
            self.set_status(response['code'])
        self.finish(response)

    def check_response_for_error(self, response):
        # Check if the HTTP requests were successful and handle exceptions
        if response.error is not None:
            try:
                response.rethrow()
            except (ValueError, OSError, tornado.httpclient.HTTPError):
                # Response code == 599 means that
                # no HTTP response was received.
                # In this case the error code should
                # become 400 indicating that the error was
                # raised because of a bad request parameter.
                if response.code == 599:
                    self.send_error(
                        400, reason=str(response.error))
                else:
                    self.send_error(
                        response.code, reason=str(response.error))
                raise tornado.httpclient.HTTPError(0)


def _extract_encoding(headers, content):
    encoding = None
    content_type = headers.get('Content-Type', '')
    if 'charset=' in content_type:
        encoding = content_type.split('charset=')[-1]
    if not encoding:
        meta_tag_match = META_TAG_PATTERN.search(content, endpos=2048)
        if meta_tag_match:
            encoding = meta_tag_match.group(1).decode('ascii', errors='ignore')
    if not encoding:
        prolog_match = XML_PROLOG_PATTERN.search(content, endpos=2048)
        if prolog_match:
            encoding = prolog_match.group(1).decode('ascii', errors='ignore')
    # Handle common mistakes and errors in encoding names
    if encoding == 'iso-8559-1':
        encoding = 'iso-8859-1'
    # Windows-1252 is so commonly mislabeled, WHATWG recommends assuming it's a
    # mistake: https://encoding.spec.whatwg.org/#names-and-labels
    if encoding == 'iso-8859-1' and 'html' in content_type:
        encoding = 'windows-1252'
    return encoding


def _decode_body(response, name, raise_if_binary=True):
    encoding = _extract_encoding(response.headers, response.body) or 'UTF-8'
    try:
        text = response.body.decode(encoding, errors='replace')
    except LookupError:
        # If the encoding we found isn't known, fall back to ascii
        text = response.body.decode('ascii', errors='replace')

    text_length = len(text)
    if text_length == 0:
        return text

    # Replace null terminators; some differs (especially those written in C)
    # don't handle them well in the middle of a string.
    text = text.replace('\u0000', '\ufffd')

    # If a significantly large portion of the document was totally undecodable,
    # it's likely this wasn't text at all, but binary data.
    if raise_if_binary and text.count('\ufffd') / text_length > 0.25:
        raise UndecodableContentError(f'The response body of `{name}` could not be decoded as {encoding}.')

    return text


def caller(func, a, b, **query_params):
    """
    A translation layer between HTTPResponses and differ functions.

    Parameters
    ----------
    func : callable
        a 'differ' function
    a : tornado.httpclient.HTTPResponse
    b : tornado.httpclient.HTTPResponse
    **query_params
        additional parameters parsed from the REST diffing request


    The function `func` may expect required and/or optional arguments. Its
    signature serves as a dependency injection scheme, specifying what it
    needs from the HTTPResponses. The following argument names have special
    meaning:

    * a_url, b_url: URL of HTTP request
    * a_body, b_body: Raw HTTP reponse body (bytes)
    * a_text, b_text: Decoded text of HTTP response body (str)

    Any other argument names in the signature will take their values from the
    REST query parameters.
    """
    # Supplement the query_parameters from the REST call with special items
    # extracted from `a` and `b`.
    query_params.setdefault('a_url', a.request.url)
    query_params.setdefault('b_url', b.request.url)
    query_params.setdefault('a_body', a.body)
    query_params.setdefault('b_body', b.body)
    query_params.setdefault('a_headers', a.headers)
    query_params.setdefault('b_headers', b.headers)

    # The differ's signature is a dependency injection scheme.
    sig = inspect.signature(func)

    raise_if_binary = not query_params.get('ignore_decoding_errors', False)
    if 'a_text' in sig.parameters:
        query_params.setdefault(
            'a_text',
            _decode_body(a, 'a', raise_if_binary=raise_if_binary))
    if 'b_text' in sig.parameters:
        query_params.setdefault(
            'b_text',
            _decode_body(b, 'b', raise_if_binary=raise_if_binary))

    kwargs = dict()
    for name, param in sig.parameters.items():
        try:
            kwargs[name] = query_params[name]
        except KeyError:
            if param.default is inspect._empty:
                # This is a required argument.
                raise KeyError("{} requires a parameter {} which was not "
                               "provided in the query"
                               "".format(func.__name__, name))
    return func(**kwargs)


class IndexHandler(BaseHandler):

    @tornado.gen.coroutine
    def get(self):
        # TODO Show swagger API or Markdown instead.
        info = {'diff_types': list(DIFF_ROUTES),
                'version': web_monitoring.__version__}
        self.write(info)


class HealthCheckHandler(BaseHandler):

    @tornado.gen.coroutine
    def get(self):
        # TODO Include more information about health here.
        # The 200 repsonse code with an empty object is just a liveness check.
        self.write({})


def make_app():
    class BoundDiffHandler(DiffHandler):
        differs = DIFF_ROUTES

    return tornado.web.Application([
        (r"/healthcheck", HealthCheckHandler),
        (r"/([A-Za-z0-9_]+)", BoundDiffHandler),
        (r"/", IndexHandler),
    ], debug=DEBUG_MODE, compress_response=True,
       diff_executor=None)


def start_app(port):
    app = make_app()
    app.listen(port)
    print(f'Starting server on port {port}')
    tornado.ioloop.IOLoop.current().start()


def cli():
    doc = """Start a diffing server.

Usage:
wm-diffing-server [--port <port>]

Options:
-h --help     Show this screen.
--version     Show version.
--port        Port. [default: 8888]
"""
    arguments = docopt(doc, version='0.0.1')
    port = int(arguments['<port>'] or 8888)
    start_app(port)


if __name__ == '__main__':
    cli()
