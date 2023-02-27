from collections import defaultdict, OrderedDict
from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from datetime import date, datetime, timezone
import logging
import re
import requests
import requests.adapters
import threading
import time
import urllib.parse
from .exceptions import SessionClosedError

logger = logging.getLogger(__name__)

URL_DATE_FORMAT = '%Y%m%d%H%M%S'
MEMENTO_URL_PATTERN = re.compile(
    r'^http(?:s)?://web.archive.org/web/(\d+)(\w\w_)?/(.+)$')
MEMENTO_URL_TEMPLATE = 'https://web.archive.org/web/{timestamp}{mode}/{url}'


def format_timestamp(value):
    """
    Format a value as a Wayback-style timestamp string.

    Parameters
    ----------
    value : str or datetime.datetime or datetime.date

    Returns
    -------
    str
    """
    if isinstance(value, str):
        return value
    elif isinstance(value, datetime):
        # Make sure we have either a naive datetime (assumed to
        # represent UTC) or convert the datetime to UTC.
        if value.tzinfo:
            value_utc = value.astimezone(timezone.utc)
        else:
            value_utc = value
        return value_utc.strftime(URL_DATE_FORMAT)
    elif isinstance(value, date):
        return value.strftime(URL_DATE_FORMAT)
    else:
        raise TypeError('Timestamp must be a datetime, date, or string')


def parse_timestamp(time_string):
    """
    Given a Wayback-style timestamp string, return an equivalent ``datetime``.
    """
    # Before parsing, try to fix invalid timestamps.
    # We've seen a handful of timestamps where "00" was inserted before the
    # month or day part of the timestamp, e.g:
    #
    #   20000008241731
    #       ^^ Month is "00"
    #
    # The Wayback team looked into some of these, and the "00" was always
    # an insertion, pushing the month or day and the following components of
    # the timestamp out by two characters. Then the seconds get truncated
    # (there's only room for 14 characters in the timestamp in the CDX index).
    # For example:
    #
    #   In raw data:   2000000824173151 (16 characters)
    #   In CDX index:  20000008241731   (Truncated to 14 characters)
    #   Correct value: 20000824173151   (Aug. 24, 2000 at 17:31:51 UTC)
    #
    # The best we can do for these cases is pull out the incorrect "00" and add
    # "00" for the seconds that got truncated. This isn't exact, but we can't
    # see the raw data so this is as close as we can get.
    #
    # The issue seems to be limited to some crawls in the year 2000.
    if time_string[5] == '0' and time_string[4] == '0':
        logger.warning("found invalid timestamp with month 00: %s", time_string)
        time_string = f'{time_string[0:4]}{time_string[6:]}00'
    elif time_string[7] == '0' and time_string[6] == '0':
        logger.warning("found invalid timestamp with day 00: %s", time_string)
        time_string = f'{time_string[0:6]}{time_string[8:]}00'

    # Parse the cleaned-up result.
    return (datetime
            .strptime(time_string, URL_DATE_FORMAT)
            .replace(tzinfo=timezone.utc))


def ensure_utc_datetime(value):
    """
    Given a datetime, date, or Wayback-style timestamp string, return an
    equivalent datetime in UTC.

    Parameters
    ----------
    value : str or datetime.datetime or datetime.date

    Returns
    -------
    datetime.datetime
    """
    if isinstance(value, str):
        return parse_timestamp(value)
    elif isinstance(value, datetime):
        if value.tzinfo:
            return value.astimezone(timezone.utc)
        else:
            return value.replace(tzinfo=timezone.utc)
    elif isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    else:
        raise TypeError('`datetime` must be a string, date, or datetime')


def clean_memento_url_component(url):
    """
    Attempt to fix encoding or other issues with the target URL that was
    embedded in a memento URL.
    """
    # A URL *may* be percent encoded, decode ONLY if so (we don’t want to
    # accidentally decode the querystring if there is one)
    lower_url = url.lower()
    if lower_url.startswith('http%3a') or lower_url.startswith('https%3a'):
        url = urllib.parse.unquote(url)

    return url


def memento_url_data(memento_url):
    """
    Get the original URL, time, and mode that a memento URL represents a
    capture of.

    Returns
    -------
    url : str
        The URL that the memento is a capture of.
    time : datetime.datetime
        The time the memento was captured in the UTC timezone.
    mode : str
        The playback mode.

    Examples
    --------
    Extract original URL, time and mode.

    >>> url = ('https://web.archive.org/web/20170813195036id_/'
    ...        'https://arpa-e.energy.gov/?q=engage/events-workshops')
    >>> memento_url_data(url)
    ('https://arpa-e.energy.gov/?q=engage/events-workshops',
     datetime.datetime(2017, 8, 13, 19, 50, 36, tzinfo=timezone.utc),
     'id_')
    """
    match = MEMENTO_URL_PATTERN.match(memento_url)
    if match is None:
        raise ValueError(f'"{memento_url}" is not a memento URL')

    url = clean_memento_url_component(match.group(3))
    date = parse_timestamp(match.group(1))
    mode = match.group(2) or ''

    return url, date, mode


def format_memento_url(url, timestamp, mode=''):
    """
    Get the URL for a memento of a given URL, timestamp, and mode.

    Parameters
    ----------
    url : str
    timestamp : str or datetime.datetime or datetime.date
    mode : str

    Returns
    -------
    str
    """
    return MEMENTO_URL_TEMPLATE.format(url=url,
                                       timestamp=format_timestamp(timestamp),
                                       mode=mode)


def set_memento_url_mode(url, mode):
    """
    Return a memento URL with the "mode" component set to the given mode. If
    the URL is not a memento URL, raises ``ValueError``.

    Parameters
    ----------
    url : str
    mode : str

    Returns
    -------
    str
    """
    captured_url, timestamp, _ = memento_url_data(url)
    return format_memento_url(captured_url, timestamp, mode)


_last_call_by_group = defaultdict(int)
_rate_limit_lock = threading.Lock()


@contextmanager
def rate_limited(calls_per_second=2, group='default'):
    """
    A context manager that restricts entries to its body to occur only N times
    per second (N can be a float). The current thread will be put to sleep in
    order to delay calls.

    Parameters
    ----------
    calls_per_second : float or int, default: 2
        Maximum number of calls into this context allowed per second
    group : string, default: 'default'
        Unique name to scope rate limiting. If two contexts have different
        `group` values, their timings will be tracked separately.
    """
    if calls_per_second <= 0:
        yield
    else:
        with _rate_limit_lock:
            last_call = _last_call_by_group[group]
            minimum_wait = 1.0 / calls_per_second
            current_time = time.time()
            if current_time - last_call < minimum_wait:
                time.sleep(minimum_wait - (current_time - last_call))
            _last_call_by_group[group] = time.time()
        yield


class DepthCountedContext:
    """
    DepthCountedContext is a mixin or base class for context managers that need
    to be perform special operations only when all nested contexts they might
    be used in have exited.

    Override the `__exit_all__(self, type, value, traceback)` method to get a
    version of `__exit__` that is only called when exiting the top context.

    As a convenience, the built-in `__enter__` returns `self`, which is fairly
    common, so in many cases you don't need to author your own `__enter__` or
    `__exit__` methods.
    """
    _context_depth = 0

    def __enter__(self):
        self._context_depth += 1
        return self

    def __exit__(self, type, value, traceback):
        if self._context_depth > 0:
            self._context_depth -= 1
        if self._context_depth == 0:
            return self.__exit_all__(type, value, traceback)

    def __exit_all__(self, type, value, traceback):
        """
        A version of the normal `__exit__` context manager method that only
        gets called when the top level context is exited. This is meant to be
        overridden in your class.
        """
        pass


class DisableAfterCloseSession(requests.Session):
    """
    A custom session object raises a :class:`SessionClosedError` if you try to
    use it after closing it, to help identify and avoid potentially dangerous
    code patterns. (Standard session objects continue to be usable after
    closing, even if they may not work exactly as expected.)
    """
    _closed = False

    def close(self, disable=True):
        super().close()
        if disable:
            self._closed = True

    def send(self, *args, **kwargs):
        if self._closed:
            raise SessionClosedError('This session has already been closed '
                                     'and cannot send new HTTP requests.')

        return super().send(*args, **kwargs)


class CaseInsensitiveDict(MutableMapping):
    """
    A case-insensitive ``dict`` subclass.

    Implements all methods and operations of ``MutableMapping`` as well as
    dict's ``copy``.

    All keys are expected to be strings. The structure remembers the case of
    the last key to be set, and ``iter(instance)``, ``keys()``, ``items()``,
    ``iterkeys()``, and ``iteritems()`` will contain case-sensitive keys.
    However, querying and contains testing is case insensitive::

      cid = CaseInsensitiveDict()
      cid['Accept'] = 'application/json'
      cid['aCCEPT'] == 'application/json'  # True
      list(cid) == ['Accept']  # True

    For example, ``headers['content-encoding']`` will return the value of a
    ``'Content-Encoding'`` response header, regardless of how the header name
    was originally stored. If the constructor, ``.update``, or equality
    comparison operations are given keys that have equal lower-case keys, the
    behavior is undefined.

    This implementation is based on Requests v2.28.0, which is available under
    the Apache 2.0 license at https://github.com/psf/requests.
    """

    def __init__(self, data=None, **kwargs):
        self._store = OrderedDict()
        if data is None:
            data = {}
        self.update(data, **kwargs)

    def __setitem__(self, key, value):
        if not isinstance(key, str):
            raise TypeError(f'The key "{key}" is not a string')

        # Use the lowercased key for lookups, but store the actual
        # key alongside the value.
        self._store[key.lower()] = (key, value)

    def __getitem__(self, key):
        return self._store[key.lower()][1]

    def __delitem__(self, key):
        del self._store[key.lower()]

    def __iter__(self):
        return (casedkey for casedkey, mappedvalue in self._store.values())

    def __len__(self):
        return len(self._store)

    def _lower_items(self):
        """Like iteritems(), but with all lowercase keys."""
        return ((lowerkey, keyval[1]) for (lowerkey, keyval) in self._store.items())

    def __eq__(self, other):
        if isinstance(other, Mapping):
            other = CaseInsensitiveDict(other)
        else:
            return NotImplemented
        # Compare insensitively
        return dict(self._lower_items()) == dict(other._lower_items())

    def copy(self):
        return CaseInsensitiveDict(self._store.values())

    def __repr__(self):
        return str(dict(self.items()))
