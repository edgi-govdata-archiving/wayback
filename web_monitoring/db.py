# This module implements Python classes that provide a restricted and validated
# interface to several databases.

# Pages: associates a URL with agency metadata
# Snapshots: assocates an HTML snapshot at a specific time with a Page
# Diffs: stores a PageFreezer (or PageFreezer-like) result for a diff of two
#        Snapshots along with a hash of that diff
# Priorities: associates a priority with a Diff
# Annotations: Human-entered information about a Diff
#
# Additionally, there is WorkQueue that wraps Priorities and Diffs and
# implements a checkout/checkin system for users requesting a Diff to annotate.

import os
import tempfile
import logging
import datetime
import collections
import uuid
import json
import hashlib
import time
import csv

import requests
import sqlalchemy

logger = logging.getLogger(__name__)

# These schemas were informed by work by @Mr0grog at
# https://github.com/edgi-govdata-archiving/webpage-versions-db/blob/master/db/schema.rb
PAGES_COLUMNS = (
    sqlalchemy.Column('uuid', sqlalchemy.Text, primary_key=True),
    sqlalchemy.Column('url', sqlalchemy.Text),
    sqlalchemy.Column('title', sqlalchemy.Text),
    sqlalchemy.Column('agency', sqlalchemy.Text),
    sqlalchemy.Column('site', sqlalchemy.Text),
    sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                      default=datetime.datetime.utcnow),
)
SNAPSHOTS_COLUMNS = (
    sqlalchemy.Column('uuid', sqlalchemy.Text, primary_key=True),
    sqlalchemy.Column('page_uuid', sqlalchemy.Text),
    sqlalchemy.Column('capture_time', sqlalchemy.DateTime),
    sqlalchemy.Column('path', sqlalchemy.Text),
    sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                      default=datetime.datetime.utcnow),
)
DIFFS_COLUMNS = (
    sqlalchemy.Column('uuid', sqlalchemy.Text, primary_key=True),
    sqlalchemy.Column('diffhash', sqlalchemy.Text),
    sqlalchemy.Column('uuid1', sqlalchemy.Text),
    sqlalchemy.Column('uuid2', sqlalchemy.Text),
    sqlalchemy.Column('path', sqlalchemy.Text),
    sqlalchemy.Column('annotation', sqlalchemy.JSON),
    sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                      default=datetime.datetime.utcnow),
)
PRIORITIES_COLUMNS = (
    sqlalchemy.Column('diff_uuid', sqlalchemy.Text, primary_key=True),
    sqlalchemy.Column('priority', sqlalchemy.Float),
    sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                      default=datetime.datetime.utcnow),
)
ANNOTATIONS_COLUMNS = (
    sqlalchemy.Column('uuid', sqlalchemy.Text, primary_key=True),
    sqlalchemy.Column('diff_uuid', sqlalchemy.Text),
    sqlalchemy.Column('annotation', sqlalchemy.types.JSON),
    sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                      default=datetime.datetime.utcnow),
)


def create(engine):
    meta = sqlalchemy.MetaData(engine)
    sqlalchemy.Table("Pages", meta, *PAGES_COLUMNS)
    sqlalchemy.Table("Snapshots", meta, *SNAPSHOTS_COLUMNS)
    sqlalchemy.Table("Diffs", meta, *DIFFS_COLUMNS)
    sqlalchemy.Table("Priorities", meta, *PRIORITIES_COLUMNS)
    sqlalchemy.Table("Annotations", meta, *ANNOTATIONS_COLUMNS)
    meta.create_all()


class Pages:
    """
    Interface to a table associating a URL with agency metadata.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
    """
    nt = collections.namedtuple('Page', 'uuid url title agency site')
    def __init__(self, engine):
        self.engine = engine
        meta = sqlalchemy.MetaData(engine)
        self.table = sqlalchemy.Table('Pages', meta, autoload=True)

    def insert(self, url, title='', agency='', site=''):
        """
        Insert a new Page into the database.

        This is a prerequisite to storing any Snapshots of the Page.

        Parameters
        ----------
        url : string
        title : string, optional
        agency : string, optional
        site : string, optional

        Returns
        -------
        uuid : string
            unique identifer assigned to this page
        """
        _uuid = str(uuid.uuid4())
        values = (_uuid, url, title, agency, site, datetime.datetime.utcnow())
        self.engine.execute(self.table.insert().values(values))
        return _uuid

    def __getitem__(self, uuid):
        "Look up a Page by its uuid."
        result = self.engine.execute(
            self.table.select().where(self.table.c.uuid == uuid)).fetchone()
        # Pack the result in a namedtuple, stripping off created_at which is
        # only for internal database debugging / recovery.
        return self.nt(*result[:-1])

    def by_url(self, url):
        """
        Find a Page by its url.
        """
        proxy = self.engine.execute(
            self.table.select()
            .where(self.table.c.url == url))
        result = proxy.fetchone()
        # Pack the result in a namedtuple, stripping off created_at which is
        # only for internal database debugging / recovery.
        return self.nt(*result[:-1])


class Snapshots:
    """
    Interface to a table associating an HTML snapshot at some time with a Page.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
    """
    unprocessed = collections.deque()
    nt = collections.namedtuple('Snapshot', 'uuid page_uuid capture_time path')

    def __init__(self, engine):
        self.engine = engine
        meta = sqlalchemy.MetaData(engine)
        self.table = sqlalchemy.Table('Snapshots', meta, autoload=True)

    def insert(self, page_uuid, capture_time, path):
        """
        Insert a new Snapshot into the database.

        Parameters
        ----------
        page_uuid : string
            referring to the Page that corresponds to this Snapshot
        capture_time : datetime.datetime
        path : string
            e.g., filepath to HTML file on disk or some other resource locator

        Returns
        -------
        uuid : string
            unique identifer assigned to this page
        """
        _uuid = str(uuid.uuid4())
        values = (_uuid, page_uuid, capture_time, path,
                  datetime.datetime.utcnow())
        self.engine.execute(self.table.insert().values(values))
        self.unprocessed.append(_uuid)
        return _uuid

    def __getitem__(self, uuid):
        "Look up a Snapshot by its uuid."
        result = self.engine.execute(
            self.table.select().where(self.table.c.uuid == uuid)).fetchone()
        # Pack the result in a namedtuple, stripping off created_at which is
        # only for internal database debugging / recovery.
        return self.nt(*result[:-1])

    def history(self, page_uuid):
        """
        Lazily yield Snapshots for a given Page in reverse chronological order.
        """
        proxy = self.engine.execute(
            self.table.select()
            .where(self.table.c.page_uuid == page_uuid)
            .order_by(sqlalchemy.desc(self.table.c.capture_time)))
        while True:
            result = proxy.fetchone()
            if result is None:
                raise StopIteration
            # As above, use a namedtuple and omit created_at.
            yield self.nt(*result[:-1])

    def oldest(self, page_uuid):
        """
        Return the oldest Snapshot for a given Page.
        """
        proxy = self.engine.execute(
            self.table.select()
            .where(self.table.c.page_uuid == page_uuid)
            .order_by(self.table.c.capture_time))
        result = proxy.fetchone()
        # As above, use a namedtuple and omit created_at.
        return self.nt(*result[:-1])


class Diffs:
    """
    Interface to an object store of PageFreezer(-like) results.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
    """
    unprocessed = collections.deque()
    nt = collections.namedtuple('Diff', 'uuid diffhash uuid1 uuid2 result '
                                        'annotation')

    def __init__(self, engine):
        self.engine = engine
        meta = sqlalchemy.MetaData(engine)
        self.table = sqlalchemy.Table('Diffs', meta, autoload=True)

    def _get_new_filepath(self):
        "Get a path to save a result JSON to."
        return tempfile.NamedTemporaryFile(delete=False).name

    def insert(self, snapshot1_uuid, snapshot2_uuid, result):
        diffs = result['output']['diffs']
        diffhash = hashlib.sha256(str(diffs).encode()).hexdigest()
        _uuid = str(uuid.uuid4())
        filepath = self._get_new_filepath()
        with open(filepath, 'w') as f:
            json.dump(result, f)
        values = (_uuid, diffhash, snapshot1_uuid, snapshot2_uuid, filepath,
                  None, datetime.datetime.utcnow())
        self.engine.execute(self.table.insert().values(values))
        self.unprocessed.append(_uuid)
        return _uuid

    def __getitem__(self, uuid):
        "Look up a Diff by its uuid."
        result = self.engine.execute(
            self.table.select().where(self.table.c.uuid == uuid)).fetchone()
        # Pack the result in a namedtuple, stripping off created_at which is
        # only for internal database debugging / recovery.
        d = self.nt(*result[:-1])
        # We store the path the file where the JSON was dumped. Load it and put
        # it into the result, replacing the path on the way out.
        path = d.result
        with open(path) as f:
            result = json.load(f)
        return d._replace(result=result)


class Priorities:
    """
    Interface to a table assigning priorities to Diffs.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
    """
    def __init__(self, engine):
        self.engine = engine
        meta = sqlalchemy.MetaData(engine)
        self.table = sqlalchemy.Table('Priorities', meta, autoload=True)

    def insert(self, diff_uuid, priority):
        """
        Record an annotation about the Diff with the given uuid.
        """
        # Note that Priorities reuses diff_uuid as the primary key;
        # it does not need to generate a separate id.
        values = (diff_uuid, priority, datetime.datetime.utcnow())
        self.engine.execute(self.table.insert().values(values))
        return diff_uuid

    def annotated(self, diff_uuid):
        """
        Delete or de-prioritize because this has been annotated.
        """
        self.engine.execute(self.table.delete()
                             .where(self.table.c.diff_uuid == diff_uuid))

    def __iter__(self):
        "a generator of diff_uuids starting with highest priority"
        proxy = self.engine.execute(
            self.table.select()
            .order_by(sqlalchemy.desc(self.table.c.priority)))
        def gen():
            for result in proxy:
                if result is None:
                    raise StopIteration
                yield result[0]  # diff_uuid
        return gen()


class WorkQueue:
    def __init__(self, priorities, diffs):
        self.priorities = priorities
        self.diffs = diffs
        self.checked_out = {}  # maps user_id to diff_uuid

    def checkout_next(self, user_id):
        for diff_uuid in self.priorities:
            if diff_uuid not in self.checked_out.values():
                # This is the highest-priority Diff not yet checked out.
                self.checked_out[user_id] = diff_uuid
                return self.diffs[diff_uuid]
        raise EmptyWorkQueue("All work is complete or checkout out.")
        
    def checkout(self, user_id, diff_uuid):
        """
        Mark this Diff as being worked on by someone currently.
        """
        if user_id in self.checked_out:
            self.checkin(user_id)
        self.checked_out[user_id] = diff_uuid
        return self.diffs[diff_uuid]

    def checkin(self, user_id):
        """
        Mark this Diff as not being worked on and not complete.
        """
        self.checked_out.pop(user_id)


class Annotations:
    """
    Interface to an object store of human-entered information about diffs.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
    """
    nt = collections.namedtuple('Annotation', 'uuid diff_uuid annotation')

    def __init__(self, engine):
        self.engine = engine
        meta = sqlalchemy.MetaData(engine)
        self.table = sqlalchemy.Table('Annotations', meta, autoload=True)

    def insert(self, diff_uuid, annotation):
        """
        Record an annotation about the Diff with the given uuid.

        Parameters
        ----------
        diff_uuid : string
            the Diff that this annotation regards
        annotation : dict
            i.e., a JSON-like blob
        """
        _uuid = str(uuid.uuid4())
        values = (_uuid, diff_uuid, annotation, datetime.datetime.utcnow())
        self.engine.execute(self.table.insert().values(values))
        return _uuid

    def __getitem__(self, uuid):
        "Look up an Annotation by its uuid."
        result = self.engine.execute(
            self.table.select().where(self.table.c.uuid == uuid)).fetchone()
        # Pack the result in a namedtuple, stripping off created_at which is
        # only for internal database debugging / recovery.
        return self.nt(*result[:-1])

    def by_diff(self, diff_uuid):
        "Look up a list of all Annotations for a given Diff."
        results = self.engine.execute(
            self.table.select()
            .where(self.table.c.diff_uuid == diff_uuid)).fetchall()
        return [self.nt(*result[:-1]) for result in results]


def compare(html1, html2):
    """
    Send a request to PageFreezer to compare two HTML snippets.

    Parameters
    ----------
    html1 : string
    html2 : string

    Returns
    -------
    response : dict
    """
    URL = 'https://api1.pagefreezer.com/v1/api/utils/diff/compare'
    data = {'source': 'text',
            'url1': html1,
            'url2': html2}
    headers = {'x-api-key': os.environ['PAGE_FREEZER_API_KEY'],
               'Accept': 'application/json',
               'Content-Type': 'application/json', }
    logger.debug("Sending PageFreezer request...")
    raw_response = requests.post(URL, data=json.dumps(data), headers=headers)
    response = raw_response.json()
    logger.debug("Response received in %.3f seconds with status %s.",
                 response.get('elapsed'), response.get('status'))
    return response


def diff_snapshot(snapshot_uuid, snapshots, diffs):
    """
    Compare a snapshot with its ancestor and store the result in Diffs.

    It might be convenient to use ``functools.partial`` to bind this to
    specific instances of Snapshots and Diffs.

    Parameters
    ----------
    snapshot_uuid : string
    snapshots : Snapshots
    diff : Diffs
    """
    # Retrieve the Snapshot for the database.
    snapshot = snapshots[snapshot_uuid]

    # Find its ancestor to compare with.
    ancestor = snapshots.oldest(snapshot.page_uuid)
    if ancestor == snapshot:
        # This is the oldest one we have -- nothing to compare!
        raise NoAncestor("This is the oldest Snapshot available for the Page "
                         "with page_uuid={}".format(snapshot.page_uuid))
    html1 = open(ancestor.path).read()
    html2 = open(snapshot.path).read()
    result = compare(html1, html2)  # PageFreezer API call
    if result['status'] != 'ok':
        raise PageFreezerError("result status is not 'ok': {}"
                                "".format(result['status']))
    diffs.insert(ancestor.uuid, snapshot.uuid, result['result'])


class WebVersioningException(Exception):
    # All exceptions raised by this package inherit from this.
    ...


class PageFreezerError(WebVersioningException):
    ...


class NoAncestor(WebVersioningException):
    ...


class EmptyWorkQueue(WebVersioningException):
    ...
