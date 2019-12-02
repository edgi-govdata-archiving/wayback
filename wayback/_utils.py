from collections import defaultdict
from contextlib import contextmanager
import requests
import requests.adapters
import threading
import time
from .exceptions import SessionClosedError


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
