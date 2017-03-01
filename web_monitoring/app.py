# DEPRECATED!!!

# This is unfinished and will probably be replaced by a Rails app.
# See db.py for the good code.

import os
import tornado.ioloop
import tornado.web
from jinja2 import Environment, FileSystemLoader
import sqlalchemy
import pymongo


SQL_DB_URI = 'sqlite3://'
MONGO_DB_URI = 'mongodb://localhost:27017/'
MONGO_DB_NAME = 'page_freezer_v1'
engine = sqlalcehmy.create_engine(SQL_DB_URI)
client = pymongo.MongoClient(MONGO_URI)

results = Results(client[MONGO_DB_NAME])
Annotations = Annotations(client[MONGO_DB_NAME])
snapshots = Snapshots(engine.connect())


template_path = os.path.join(os.path.dirname(__file__), 'views')
env = Environment(loader=FileSystemLoader(template_path))


class DiffHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(env.get_template('main.html').render())


class NextHandler(tornado.web.RequestHandler):
    def get(self):
        uid = next(diffs)
        self.redirect('/diff/%s' % uid)


def make_app():
    return tornado.web.Application([
        (r"/diff/", MainHandler),
        (r"/next/", NextHandler),
    ])

if __name__ == "__main__":
    app = make_app()
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()
