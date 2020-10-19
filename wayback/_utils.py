from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
import re
import requests
import requests.adapters
import threading
import time
import urllib.parse
from .exceptions import SessionClosedError


URL_DATE_FORMAT = '%Y%m%d%H%M%S'
MEMENTO_URL_PATTERN = re.compile(
    r'^http(?:s)?://web.archive.org/web/(\d+)(\w\w_)?/(.+)$')


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

    >>> url = ('http://web.archive.org/web/20170813195036id_/'
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
    calls_per_second : float or int, optional
        Maximum number of calls into this context allowed per second
    group : string, optional
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
