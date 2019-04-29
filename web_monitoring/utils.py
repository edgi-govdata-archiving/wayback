from collections import defaultdict
from contextlib import contextmanager
import hashlib
import io
import lxml.html
import os
import requests
import time


def extract_title(content_bytes, encoding='utf-8'):
    "Return content of <title> tag as string. On failure return empty string."
    content_str = content_bytes.decode(encoding=encoding, errors='ignore')
    # The parser expects a file-like, so we mock one.
    content_as_file = io.StringIO(content_str)
    try:
        title = lxml.html.parse(content_as_file).find(".//title")
    except Exception:
        return ''
    if title is None:
        return ''
    else:
        return title.text


def hash_content(content_bytes):
    "Create a version_hash for the content of a snapshot."
    return hashlib.sha256(content_bytes).hexdigest()


def _should_retry(response):
    return response.status_code == 503 or response.status_code == 504


def retryable_request(method, url, retries=3, backoff=20,
                      should_retry=_should_retry, session=None, **kwargs):
    """
    Make a request with the `requests` library that will be automatically
    retried up to a set number of times.

    Parameters
    ----------
    method : string
        HTTP request method to use
    url : string
        URL to request data from
    retries : int, optional
        Maximum number of retries
    backoff : int or float, optional
        Maximum number of seconds to wait before retrying. After each attempt,
        the wait time is calculated by: `backoff / retries_left`, so the final
        attempt will occur `backoff` seconds after the penultimate attempt.
    should_retry : function, optional
        A callback that receives the HTTP response and returns a boolean
        indicating whether the call should be retried. By default, it retries
        for responses with 503 and 504 status codes (gateway errors).
    session : requests.Session, optional
        A session object to use when making requests.
    **kwargs : dict, optional
        Any additional keyword parameters are passed on to `requests`

    Returns
    -------
    response : requests.Response
        The HTTP response object from `requests`
    """
    internal_session = session or requests.Session()
    response = internal_session.request(method, url, **kwargs)
    if should_retry(response) and retries > 0:
        time.sleep(backoff / retries)
        response = retryable_request(method, url, retries - 1, backoff,
                                     session=internal_session, **kwargs)

    if internal_session is not session:
        internal_session.close()

    return response


_last_call_by_group = defaultdict(int)


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
        last_call = _last_call_by_group[group]
        minimum_wait = 1.0 / calls_per_second
        current_time = time.time()
        if current_time - last_call < minimum_wait:
            time.sleep(minimum_wait - (current_time - last_call))
        yield
        _last_call_by_group[group] = time.time()


def get_color_palette():
    """
    Read and return the CSS color env variables that indicate the colors in
    html_diff_render, differs and links_diff.

    Returns
    ------
    palette: Dictionary
        A dictionary containing the differ_insertion and differ_deletion css
        color codes
    """
    differ_insertion = os.environ.get('DIFFER_COLOR_INSERTION', '#a1d76a')
    differ_deletion = os.environ.get('DIFFER_COLOR_DELETION', '#e8a4c8')
    return {'differ_insertion': differ_insertion,
            'differ_deletion': differ_deletion}
