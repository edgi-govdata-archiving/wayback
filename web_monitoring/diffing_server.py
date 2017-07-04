import concurrent.futures
from docopt import docopt
import hashlib
from importlib import import_module
import json
import tornado.gen
import tornado.httpclient
import tornado.ioloop
import tornado.web


def load_config(config):
    """

    Example
    -------

    >>> load_config({'foo', ('mypackage.mymodule', 'foofunc')})
    """
    d = {}
    for name, spec in config.items():
        modname, funcname = spec
        mod = import_module(modname)
        func = getattr(mod, funcname)
        d[name] = func
    return d


client = tornado.httpclient.AsyncHTTPClient()
executor = concurrent.futures.ProcessPoolExecutor()


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
                    self.send_error(500)
                    return

        # TODO Add caching of fetched URIs.

        # Pass the bytes and any remaining args to the diffing function.
        res = yield executor.submit(func, res_a.body, res_b.body,
                                    **query_params)
        self.write(json.dumps({'diff': res}))


def make_app(config):

    class BoundDiffHandler(DiffHandler):
        differs = load_config(config)

    return tornado.web.Application([
        (r"/([A-Za-z0-9_]+)", BoundDiffHandler),
    ])

def start_app(config, port):
    app = make_app(config)
    app.listen(port)
    print(f'Starting server on port {port}')
    tornado.ioloop.IOLoop.current().start()


def cli():
    doc = """Start a diffing server.

Usage:
wm-diffing-server <config_file> [--port <port>]

Options:
-h --help     Show this screen.
--version     Show version.
--port        Port. [default: 8888]
"""
    arguments = docopt(doc, version='0.0.1')
    with open(arguments['<config_file>']) as f:
        config = json.load(f)
    port = int(arguments['<port>'] or 8888)
    start_app(config, port)
