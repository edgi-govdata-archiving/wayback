import concurrent.futures
from docopt import docopt
import hashlib
import inspect
import os
import re
import tornado.gen
import tornado.httpclient
import tornado.ioloop
import tornado.web
import traceback
import web_monitoring
import web_monitoring.differs
from web_monitoring.diff_errors import (
    UndiffableContentError, UndecodableContentError
)
import web_monitoring.html_diff_render
import web_monitoring.links_diff

# Map tokens in the REST API to functions in modules.
# The modules do not have to be part of the web_monitoring package.
DIFF_ROUTES = {
    "length": web_monitoring.differs.compare_length,
    "identical_bytes": web_monitoring.differs.identical_bytes,
    "pagefreezer": web_monitoring.differs.pagefreezer,
    "side_by_side_text": web_monitoring.differs.side_by_side_text,
    "links": web_monitoring.links_diff.links_diff,
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
debug_mode = (os.environ['TORNADO_DEBUG_MODE'] == 'True')


class DiffHandler(tornado.web.RequestHandler):
    # subclass must define `differs` attribute

    @tornado.gen.coroutine
    def get(self, differ):
        # Find the diffing function registered with the name given by `differ`.
        try:
            func = self.differs[differ]
        except KeyError:
            self.send_error(404)
            return

        # If params repeat, take last one. Decode bytes into unicode strings.
        query_params = {k: v[-1].decode() for k, v in
                        self.request.arguments.items()}
        a = query_params.pop('a')
        b = query_params.pop('b')

        # Fetch server response for URLs a and b.
        res_a, res_b = yield [client.fetch(a), client.fetch(b)]

        # Validate response bytes against hash, if provided.
        for query_param, res in zip(('a_hash', 'b_hash'), (res_a, res_b)):
            try:
                expected_hash = query_params.pop('a_hash')
            except KeyError:
                # No hash provided in the request. Skip validation.
                pass
            else:
                actual_hash = hashlib.sha256(res.body).hexdigest()
                if actual_hash != expected_hash:
                    self.send_error(
                        500, reason="Fetched content does not match hash.")
                    return

        # TODO Add caching of fetched URIs.

        # Pass the bytes and any remaining args to the diffing function.
        executor = concurrent.futures.ProcessPoolExecutor()
        res = yield executor.submit(caller, func, res_a, res_b, **query_params)
        res['version'] = web_monitoring.__version__
        # Echo the client's request unless the differ func has specified
        # somethine else.
        res.setdefault('type', differ)
        self.write(res)

    def write_error(self, status_code, **kwargs):
        response = {'code': status_code, 'error': self._reason}

        # Handle errors that are allowed to be public
        actual_error = 'exc_info' in kwargs and kwargs['exc_info'][1] or None
        if isinstance(actual_error, (UndiffableContentError,
                                     UndecodableContentError)):
            response['code'] = 422
            response['error'] = str(actual_error)

        # Fill in full info if configured to do so
        if self.settings.get('serve_traceback') and 'exc_info' in kwargs:
            response['error'] = str(kwargs['exc_info'][1])
            stack_lines = traceback.format_exception(*kwargs['exc_info'])
            response['stack'] = ''.join(stack_lines)

        if response['code'] != status_code:
            self.set_status(response['code'])
        self.finish(response)


def _extract_encoding(headers, content):
    encoding = None
    content_type = headers["Content-Type"]
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
    return encoding


def _decode_body(response, name, ignore_errors=False):
    encoding = _extract_encoding(response.headers, response.body) or 'UTF-8'
    try:
        errors = ignore_errors and 'ignore' or 'strict'
        return response.body.decode(encoding, errors=errors)
    except UnicodeError as error:
        raise UndecodableContentError(
            'The response body of `{}` could not be decoded as {}.'.format(
                name, error.encoding))


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

    ignore_decoding_errors = query_params.get(
        'ignore_decoding_errors', 'false'
    ).lower() != 'false'

    if 'a_text' in sig.parameters:
        query_params.setdefault(
            'a_text',
            _decode_body(a, 'a', ignore_decoding_errors))
    if 'b_text' in sig.parameters:
        query_params.setdefault(
            'b_text',
            _decode_body(b, 'b', ignore_decoding_errors))

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


class IndexHandler(tornado.web.RequestHandler):

    @tornado.gen.coroutine
    def get(self):
        # Return a list of the differs.
        # TODO Show swagger API or Markdown instead.
        self.write(repr(list(DIFF_ROUTES)))


def make_app():

    class BoundDiffHandler(DiffHandler):
        differs = DIFF_ROUTES

    return tornado.web.Application([
        (r"/([A-Za-z0-9_]+)", BoundDiffHandler),
        (r"/", IndexHandler),
    ], debug=debug_mode)

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
