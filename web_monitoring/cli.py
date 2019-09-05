"""
Command-Line Tools for loading data from the Wayback Machine and importing it
into web-monitoring-db

See the `scripts/` directory for the associated executable(s). Most of the
logic is implemented in this module to make it easier to test or reuse.

There is a lot of asynchronous, thread-based logic here to make sure large
import jobs can be performed efficiently, making as many parallel network
requests as Wayback and your local machine will comfortably support. The
general data flow looks something like:

   (start here)         (or here)
 ┌──────────────┐   ┌──────────────┐
 │ Create list  │   │ Load list of │
 │ of arbitrary │   │  known URLs  │
 │    URLs      │   │   from API   │
 └──────────────┘   └──────────────┘
        ├───────────────────┘
        │
 ┌─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ (in parallel) ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
 ┊      │                                                                     ┊
 ┊ ┌──────────┐  ┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  ┌────────┐ ┊
 ┊ │ Load CDX │  ┊ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┊  │ Import │ ┊
 ┊ │ records  │  ┊ │Load memento│ │Load memento│ │Load memento│ ┊  │   to   │ ┊
 ┊ │ for URLs │  ┊ └────────────┘ └────────────┘ └────────────┘ ┊  │   DB   │ ┊
 ┊ │          │  ┊    ├─────────────────┴──────────────┘        ┊  │        │ ┊
 ┊ └──────────┘  └─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  └────────┘ ┊
 ┊      ↓             ↑                              ↓   ↓           ↑   │    ┊
 ┊      └── (queue) ──┘ <─── (re-queue errors x2) ───┘   └─ (queue) ─┘   │    ┊
 ┊                                                                       │    ┊
 └─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┼─ ─ ┘
                                                                         │
                                                                       Done!

Each box represents a thread. Instances of `FiniteQueue` are used to move data
and results between them.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from docopt import docopt
import json
import logging
from os.path import splitext
import pandas
from pathlib import Path
import re
import requests
import signal
import sys
import threading
from tqdm import tqdm
from urllib.parse import urlparse
from web_monitoring import db
from web_monitoring import internetarchive as ia
from web_monitoring import utils


logger = logging.getLogger(__name__)

# Number of memento requests to make at once. Can be overridden via CLI args.
PARALLEL_REQUESTS = 10

# Matches the host segment of a URL.
HOST_EXPRESSION = re.compile(r'^[^:]+://([^/]+)')
# Matches URLs for "index" pages that are likely to be the same as a URL ending
# with a slash. e.g. matches the `index.html` in `https://epa.gov/index.html`.
# Used to group URLs representing the same logical page.
INDEX_PAGE_EXPRESSION = re.compile(r'index(\.\w+)?$')
# MIME types that we always consider to be subresources and never "pages".
SUBRESOURCE_MIME_TYPES = (
    'text/css',
    'text/javascript',
    'application/javascript',
    'image/jpeg',
    'image/webp',
    'image/png',
    'image/gif',
    'image/bmp',
    'image/tiff',
    'image/x-icon',
)
# Extensions that we always consider to be subresources and never "pages".
SUBRESOURCE_EXTENSIONS = (
    '.css',
    '.js',
    '.es',
    '.es6',
    '.jsm',
    '.jpg',
    '.jpeg',
    '.webp',
    '.png',
    '.gif',
    '.bmp',
    '.tif',
    '.ico',
)
# Never query CDX for *all* snapshots at any of these domains (instead, always
# query for each specific URL we want). This is usually because we assume these
# domains are HUGE and completely impractical to query all pages on.
NEVER_QUERY_DOMAINS = (
    'instagram.com',
    'youtube.com',
    'amazon.com'
)
# Query an entire domain for snapshots if we are interested in more than this
# many URLs in the domain (NEVER_QUERY_DOMAINS above overrides this).
MAX_QUERY_URLS_PER_DOMAIN = 30


# These functions lump together library code into monolithic operations for the
# CLI. They also print. To access this functionality programmatically, it is
# better to use the underlying library code.

def _get_progress_meter(iterable):
    # Use TQDM in all environments, but don't update very often if not a TTY.
    # Basically, the idea here is to keep TQDM in our logs so we get stats, but
    # not to waste a huge amount of space in the logs with it.
    # NOTE: This is cribbed from TQDM's `disable=None` logic:
    # https://github.com/tqdm/tqdm/blob/f2a60d1fb9e8a15baf926b4a67c02f90e0033eba/tqdm/_tqdm.py#L817-L830
    file = sys.stderr
    intervals = {}
    if hasattr(file, "isatty") and not file.isatty():
        intervals = dict(mininterval=10, maxinterval=60)

    return tqdm(iterable, desc='importing', unit=' versions', **intervals)


def _add_and_monitor(versions, create_pages=True, skip_unchanged_versions=True, stop_event=None):
    cli = db.Client.from_env()  # will raise if env vars not set
    # Wrap verions in a progress bar.
    # TODO: create this on the main thread so we can update totals when we
    # discover them in CDX, but update progress here as we import.
    versions = _get_progress_meter(versions)
    import_ids = cli.add_versions(versions, create_pages=create_pages,
                                  skip_unchanged_versions=skip_unchanged_versions)
    print('Import jobs IDs: {}'.format(import_ids))
    print('Polling web-monitoring-db until import jobs are finished...')
    errors = cli.monitor_import_statuses(import_ids, stop_event)
    if errors:
        print("Errors: {}".format(errors))


def _log_adds(versions):
    versions = _get_progress_meter(versions)
    for version in versions:
        print(json.dumps(version))


class WaybackRecordsWorker(threading.Thread):
    """
    WaybackRecordsWorker is a thread that takes CDX records from a queue and
    loads the corresponding mementos from Wayback. It then transforms the
    mementos into Web Monitoring import records and emits them on another
    queue. If a `failure_queue` is provided, records that fail to load in a way
    that might be worth retrying are emitted on that queue.
    """

    def __init__(self, records, results_queue, maintainers, tags, cancel,
                 failure_queue=None, session_options=None,
                 unplaybackable=None):
        super().__init__()
        self.summary = self.create_summary()
        self.results_queue = results_queue
        self.failure_queue = failure_queue
        self.cancel = cancel
        self.records = records
        self.maintainers = maintainers
        self.tags = tags
        self.unplaybackable = unplaybackable
        session_options = session_options or dict(retries=3, backoff=2,
                                                  timeout=(30.5, 2))
        session = ia.WaybackSession(**session_options)
        self.wayback = ia.WaybackClient(session=session)

    def is_active(self):
        return not self.cancel.is_set()

    def run(self):
        """
        Work through the queue of CDX records to load them from Wayback,
        transform them to Web Monitoring DB import entries, and queue them for
        importing.
        """
        while self.is_active():
            try:
                record = next(self.records)
                self.summary['total'] += 1
            except StopIteration:
                break

            self.handle_record(record, retry_connection_failures=True)

        self.wayback.close()
        return self.summary

    def handle_record(self, record, retry_connection_failures=False):
        """
        Handle a single CDX record.
        """
        # Check for whether we already know this can't be played and bail out.
        if self.unplaybackable is not None and record.raw_url in self.unplaybackable:
            self.summary['playback'] += 1
            return

        try:
            version = self.process_record(record, retry_connection_failures=True)
            self.results_queue.put(version)
            self.summary['success'] += 1
        except ia.MementoPlaybackError as error:
            self.summary['playback'] += 1
            if self.unplaybackable is not None:
                self.unplaybackable[record.raw_url] = datetime.utcnow()
            logger.info(f'  {error}')
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404:
                logger.info(f'  Missing memento: {record.raw_url}')
                self.summary['missing'] += 1
            else:
                # TODO: consider not logging this at a lower level, like debug
                # unless failure_queue does not exist. Unsure how big a deal
                # this error is to log if we are retrying.
                logger.info(f'  (HTTPError) {error}')
                if self.failure_queue:
                    self.failure_queue.put(record)
                else:
                    self.summary['unknown'] += 1
        except ia.WaybackRetryError as error:
            logger.info(f'  {error}; URL: {record.raw_url}')

            if self.failure_queue:
                self.failure_queue.put(record)
            else:
                self.summary['unknown'] += 1
        except Exception as error:
            # FIXME: getting read timed out connection errors here...
            # requests.exceptions.ConnectionError: HTTPConnectionPool(host='web.archive.org', port=80): Read timed out.
            # TODO: don't count or log (well, maybe DEBUG log) if failure_queue
            # is present and we are ultimately going to retry.
            logger.exception(f'  {error!r}; URL: {record.raw_url}')

            if self.failure_queue:
                self.failure_queue.put(record)
            else:
                self.summary['unknown'] += 1

    def process_record(self, record, retry_connection_failures=False):
        """
        Load the actual Wayback memento for a CDX record and transform it to
        a Web Monitoring DB import record.
        """
        try:
            return self.wayback.timestamped_uri_to_version(record.date,
                                                           record.raw_url,
                                                           url=record.url,
                                                           maintainers=self.maintainers,
                                                           tags=self.tags,
                                                           view_url=record.view_url)
        except Exception as error:
            # On connection failures, reset the session and try again. If we
            # don't do this, the connection pool for this thread is pretty much
            # dead. It's not clear to me whether there is a problem in urllib3
            # or Wayback's servers that requires this.
            # This unfortunately requires string checking because the error can
            # get wrapped up into multiple kinds of higher-level errors :(
            if retry_connection_failures and ('failed to establish a new connection' in str(error).lower()):
                self.wayback.session.reset()
                return self.process_record(record)

            # Otherwise, re-raise the error.
            raise error

    @classmethod
    def create_summary(cls):
        """
        Create a dictionary that summarizes the results of processing all the
        CDX records on a queue.
        """
        return {'total': 0, 'success': 0, 'playback': 0, 'missing': 0,
                'unknown': 0}

    @classmethod
    def summarize(cls, workers, initial=None):
        """
        Combine the summaries from multiple `WaybackRecordsWorker` instances
        into a single summary.
        """
        return cls.merge_summaries((w.summary for w in workers), initial)

    @classmethod
    def merge_summaries(cls, summaries, intial=None):
        merged = intial or cls.create_summary()
        for summary in summaries:
            for key in merged.keys():
                if key in summary:
                    merged[key] += summary[key]

        # Add percentage calculations
        if merged['total']:
            merged.update({f'{k}_pct': 100 * v / merged['total']
                           for k, v in merged.items()
                           if k != 'total' and not k.endswith('_pct')})
        else:
            merged.update({f'{k}_pct': 0.0
                           for k, v in merged.items()
                           if k != 'total' and not k.endswith('_pct')})

        return merged

    @classmethod
    def parallel(cls, count, *args, **kwargs):
        """
        Run several `WaybackRecordsWorker` instances in parallel. When this
        returns, the workers will have finished running.

        Parameters
        ----------
        count: int
            Number of instances to run in parallel.
        *args
            Arguments to pass to each instance.
        **kwargs
            Keyword arguments to pass to each instance.

        Returns
        -------
        list of WaybackRecordsWorker
        """
        workers = []
        for i in range(count):
            worker = cls(*args, **kwargs)
            workers.append(worker)
            worker.start()

        for worker in workers:
            worker.join()

        return workers

    @classmethod
    def parallel_with_retries(cls, count, summary, records, results_queue, *args, tries=None, **kwargs):
        """
        Run several `WaybackRecordsWorker` instances in parallel and retry
        records that fail to load.

        Parameters
        ----------
        count: int
            Number of instances to run in parallel.
        summary: dict
            Dictionary to populate with summary data from all worker runs.
        records: web_monitoring.utils.FiniteQueue
            Queue of CDX records to load mementos for.
        results_queue: web_monitoring.utils.FiniteQueue
            Queue to place resulting import records onto.
        *args
            Arguments to pass to each instance.
        **kwargs
            Keyword arguments to pass to each instance.

        Returns
        -------
        list of WaybackRecordsWorker
        """
        if tries is None or len(tries) == 0:
            tries = (None,)

        # Initialize the summary (we have to keep a reference so other threads can read)
        summary.update(cls.create_summary())

        total_tries = len(tries)
        retry_queue = None
        workers = []
        for index, try_setting in enumerate(tries):
            if retry_queue and not retry_queue.empty():
                print(f'\nRetrying about {retry_queue.qsize()} failed records...', flush=True)
                retry_queue.end()
                records = retry_queue

            if index == total_tries - 1:
                retry_queue = None
            else:
                retry_queue = utils.FiniteQueue()

            workers.extend(cls.parallel(count, records, results_queue, *args, **kwargs))

        summary.update(cls.summarize(workers, summary))
        results_queue.end()


def import_ia_db_urls(*, from_date=None, to_date=None, maintainers=None,
                      tags=None, skip_unchanged='resolved-response',
                      url_pattern=None, worker_count=0,
                      unplaybackable_path=None, dry_run=False):
    client = db.Client.from_env()
    logger.info('Loading known pages from web-monitoring-db instance...')
    urls, version_filter = _get_db_page_url_info(client, url_pattern)

    # Wayback search treats URLs as SURT, so dedupe obvious repeats first.
    www_subdomain = re.compile(r'^https?://www\d*\.')
    urls = set((www_subdomain.sub('http://', url) for url in urls))

    logger.info(f'Found {len(urls)} CDX-queryable URLs')
    logger.debug('\n  '.join(urls))

    return import_ia_urls(
        urls=urls,
        from_date=from_date,
        to_date=to_date,
        maintainers=maintainers,
        tags=tags,
        skip_unchanged=skip_unchanged,
        version_filter=version_filter,
        worker_count=worker_count,
        create_pages=False,
        unplaybackable_path=unplaybackable_path,
        dry_run=dry_run)


# TODO: this function probably be split apart so `dry_run` doesn't need to
# exist as an argument.
def import_ia_urls(urls, *, from_date=None, to_date=None,
                   maintainers=None, tags=None,
                   skip_unchanged='resolved-response',
                   version_filter=None, worker_count=0,
                   create_pages=True, unplaybackable_path=None,
                   dry_run=False):
    skip_responses = skip_unchanged == 'response'
    worker_count = worker_count if worker_count > 0 else PARALLEL_REQUESTS
    unplaybackable = load_unplaybackable_mementos(unplaybackable_path)

    with utils.QuitSignal((signal.SIGINT, signal.SIGTERM)) as stop_event:
        cdx_records = utils.FiniteQueue()
        cdx_thread = threading.Thread(target=lambda: utils.iterate_into_queue(
            cdx_records,
            _list_ia_versions_for_urls(
                urls,
                from_date,
                to_date,
                skip_responses,
                version_filter,
                # Use a custom session to make sure CDX calls are extra robust.
                client=ia.WaybackClient(ia.WaybackSession(retries=10, backoff=4)),
                stop=stop_event)))
        cdx_thread.start()

        summary = {}
        versions_queue = utils.FiniteQueue()
        memento_thread = threading.Thread(target=lambda: WaybackRecordsWorker.parallel_with_retries(
            worker_count,
            summary,
            cdx_records,
            versions_queue,
            maintainers,
            tags,
            stop_event,
            unplaybackable,
            tries=(None,
                   dict(retries=3, backoff=4, timeout=(30.5, 2)),
                   dict(retries=7, backoff=4, timeout=60.5))))
        memento_thread.start()

        uploadable_versions = versions_queue
        if skip_unchanged == 'resolved-response':
            uploadable_versions = _filter_unchanged_versions(versions_queue)
        if dry_run:
            uploader = threading.Thread(target=lambda: _log_adds(uploadable_versions))
        else:
            uploader = threading.Thread(target=lambda: _add_and_monitor(uploadable_versions, create_pages, stop_event))
        uploader.start()

        cdx_thread.join()
        memento_thread.join()

        print('\nLoaded {total} CDX records:\n'
              '  {success:6} successes ({success_pct:.2f}%),\n'
              '  {playback:6} could not be played back ({playback_pct:.2f}%),\n'
              '  {missing:6} had no actual memento ({missing_pct:.2f}%),\n'
              '  {unknown:6} unknown errors ({unknown_pct:.2f}%).'.format(
                **summary))

        uploader.join()

        if not dry_run:
            print('Saving list of non-playbackable URLs...')
            save_unplaybackable_mementos(unplaybackable_path, unplaybackable)


def _filter_unchanged_versions(versions):
    """
    Take an iteratable of importable version dicts and yield only versions that
    differ from the previous version of the same page.
    """
    last_hashes = {}
    for version in versions:
        if last_hashes.get(version['page_url']) != version['version_hash']:
            last_hashes[version['page_url']] = version['version_hash']
            yield version


def _list_ia_versions_for_urls(url_patterns, from_date, to_date,
                               skip_repeats=True, version_filter=None,
                               client=None, stop=None):
    version_filter = version_filter or _is_page
    skipped = 0

    with client or ia.WaybackClient() as client:
        for url in url_patterns:
            if stop and stop.is_set():
                break

            ia_versions = client.list_versions(url,
                                            from_date=from_date,
                                            to_date=to_date,
                                            skip_repeats=skip_repeats)
            try:
                for version in ia_versions:
                    if stop and stop.is_set():
                        break
                    if version_filter(version):
                        yield version
                    else:
                        skipped += 1
                        logger.debug('Skipping URL "%s"', version.url)
            except ia.BlockedByRobotsError as error:
                logger.warn(f'CDX search error: {error!r}')
            except ValueError as error:
                # NOTE: this isn't really an exceptional case; list_versions()
                # raises ValueError when Wayback has no matching records.
                # TODO: there should probably be no exception in this case.
                if 'does not have archived versions' not in str(error):
                    logger.warn(repr(error))
            except ia.WaybackException as error:
                logger.error(f'Error getting CDX data for {url}: {error!r}')
            except Exception:
                # Need to handle the exception here to let iteration continue
                # and allow other threads that might be running to be joined.
                logger.exception(f'Error processing versions of {url}')

    if skipped > 0:
        logger.info('Skipped %s URLs that did not match filters', skipped)


def load_unplaybackable_mementos(path):
    unplaybackable = {}
    if path:
        try:
            with open(path) as file:
                unplaybackable = json.load(file)
        except FileNotFoundError:
            pass
    return unplaybackable


def save_unplaybackable_mementos(path, mementos, expiration=7 * 24 * 60 * 60):
    if path is None:
        return

    threshold = datetime.utcnow() - timedelta(seconds=expiration)
    urls = list(mementos.keys())
    for url in urls:
        date = mementos[url]
        needs_format = False
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%dT%H:%M:%SZ')
        else:
            needs_format = True

        if date < threshold:
            del mementos[url]
        elif needs_format:
            mementos[url] = date.isoformat(timespec='seconds') + 'Z'

    file_path = Path(path)
    if not file_path.parent.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open('w') as file:
        json.dump(mementos, file)


def _can_query_domain(domain):
    if domain in NEVER_QUERY_DOMAINS:
        return False

    return next((False for item in NEVER_QUERY_DOMAINS
                if domain.endswith(f'.{item}')), True)


def _get_db_page_url_info(client, url_pattern=None):
    # If these sets get too big, we can switch to a bloom filter. It's fine if
    # we have some false positives. Any noise reduction is worthwhile.
    url_keys = set()
    domains = defaultdict(lambda: {'query_domain': False, 'urls': []})

    domains_without_url_keys = set()
    for page in _list_all_db_pages(client, url_pattern):
        domain = HOST_EXPRESSION.match(page['url']).group(1)
        data = domains[domain]
        if not data['query_domain']:
            if len(data['urls']) >= MAX_QUERY_URLS_PER_DOMAIN and _can_query_domain(domain):
                data['query_domain'] = True
            else:
                data['urls'].append(page['url'])

        if domain in domains_without_url_keys:
            continue

        url_key = page['url_key']
        if url_key:
            url_keys.add(_rough_url_key(url_key))
        else:
            domains_without_url_keys.add(domain)
            logger.warn('Found DB page with no url_key; *all* pages in '
                        f'"{domain}" will be imported')

    def filterer(version, domain=None):
        domain = domain or HOST_EXPRESSION.match(version.url).group(1)
        if domain in domains_without_url_keys:
            return _is_page(version)
        else:
            return _rough_url_key(version.key) in url_keys

    url_list = []
    for domain, data in domains.items():
        if data['query_domain']:
            url_list.append(f'http://{domain}/*')
        else:
            url_list.extend(data['urls'])

    return url_list, filterer


def _rough_url_key(url_key):
    """
    Create an ultra-loose version of a SURT key that should match regardless of
    most SURT settings. (This allows lots of false positives.)
    """
    rough_key = url_key.lower()
    rough_key = rough_key.split('?', 1)[0]
    rough_key = rough_key.split('#', 1)[0]
    rough_key = INDEX_PAGE_EXPRESSION.sub('', rough_key)
    if rough_key.endswith('/'):
        rough_key = rough_key[:-1]
    return rough_key


def _is_page(version):
    """
    Determine if a version might be a page we want to track. This is used to do
    some really simplistic filtering on noisy Internet Archive results if we
    aren't filtering down to a explicit list of URLs.
    """
    return (version.mime_type not in SUBRESOURCE_MIME_TYPES and
            splitext(urlparse(version.url).path)[1] not in SUBRESOURCE_EXTENSIONS)


# TODO: this should probably be a method on db.Client, but db.Client could also
# do well to transform the `links` into callables, e.g:
#     more_pages = pages['links']['next']()
def _list_all_db_pages(client, url_pattern=None):
    chunk = 1
    while chunk > 0:
        pages = client.list_pages(sort=['created_at:asc'], chunk_size=1000,
                                  chunk=chunk, url=url_pattern, active=True)
        yield from pages['data']
        chunk = pages['links']['next'] and (chunk + 1) or -1


def _parse_date_argument(date_string):
    """Parse a CLI argument that should represent a date into a datetime"""
    if not date_string:
        return None

    try:
        hours = float(date_string)
        return datetime.utcnow() - timedelta(hours=hours)
    except ValueError:
        pass

    try:
        parsed = pandas.to_datetime(date_string)
        if not pandas.isnull(parsed):
            return parsed
    except ValueError:
        pass

    return None


def main():
    doc = f"""Command Line Interface to the web_monitoring Python package

Usage:
wm import ia <url> [--from <from_date>] [--to <to_date>] [--tag <tag>...] [--maintainer <maintainer>...] [options]
wm import ia-known-pages [--from <from_date>] [--to <to_date>] [--pattern <url_pattern>] [--tag <tag>...] [--maintainer <maintainer>...] [options]

Options:
-h --help                     Show this screen.
--version                     Show version.
--maintainer <maintainer>     Name of entity that maintains the imported pages.
                              Repeat to add multiple maintainers.
--tag <tag>                   Tags to apply to pages. Repeat for multiple tags.
--skip-unchanged <skip_type>  Skip consecutive captures of the same content.
                              Can be:
                                `none` (no skipping),
                                `response` (if the response is unchanged), or
                                `resolved-response` (if the final response
                                    after redirects is unchanged)
                              [default: resolved-response]
--pattern <url_pattern>       A pattern to match when retrieving URLs from a
                              web-monitoring-db instance.
--parallel <parallel_count>   Number of parallel network requests to support.
                              [default: {PARALLEL_REQUESTS}]
--unplaybackable <play_path>  A file in which to list memento URLs that can not
                              be played back. When importing is complete, a
                              list of unplaybackable mementos will be written
                              to this file. If it exists before importing,
                              memento URLs listed in it will be skipped.
--dry-run                     Don't upload data to web-monitoring-db.
"""
    arguments = docopt(doc, version='0.0.1')
    if arguments['import']:
        skip_unchanged = arguments['--skip-unchanged']
        if skip_unchanged not in ('none', 'response', 'resolved-response'):
            print('--skip-unchanged must be one of `none`, `response`, '
                  'or `resolved-response`')
            return

        if arguments['ia']:
            import_ia_urls(
                urls=[arguments['<url>']],
                maintainers=arguments.get('--maintainer'),
                tags=arguments.get('--tag'),
                from_date=_parse_date_argument(arguments['<from_date>']),
                to_date=_parse_date_argument(arguments['<to_date>']),
                skip_unchanged=skip_unchanged,
                unplaybackable_path=arguments.get('--unplaybackable'),
                dry_run=arguments.get('--dry-run'))
        elif arguments['ia-known-pages']:
            import_ia_db_urls(
                from_date=_parse_date_argument(arguments['<from_date>']),
                to_date=_parse_date_argument(arguments['<to_date>']),
                maintainers=arguments.get('--maintainer'),
                tags=arguments.get('--tag'),
                skip_unchanged=skip_unchanged,
                url_pattern=arguments.get('--pattern'),
                worker_count=int(arguments.get('--parallel')),
                unplaybackable_path=arguments.get('--unplaybackable'),
                dry_run=arguments.get('--dry-run'))


if __name__ == '__main__':
    main()
