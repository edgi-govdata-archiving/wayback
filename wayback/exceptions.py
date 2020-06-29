"""
Exception classes that may be raised from the Wayback package.
"""


class WaybackException(Exception):
    "Base exception class for all Wayback-specific errors."


class UnexpectedResponseFormat(WaybackException):
    """
    Raised when data returned by the Wayback Machine is formatted in an
    unexpected or unparseable way.
    """


class BlockedByRobotsError(WaybackException):
    """
    Raised when a URL can't be queried in Wayback because it was blocked by a
    site's `robots.txt` file.
    """


class BlockedSiteError(WaybackException):
    """
    Raised when a URL has been blocked from access or querying in Wayback. This
    is often because of a takedown request. (URLs that are blocked because of
    ``robots.txt`` get a ``BlockedByRobotsError`` instead.)
    """


# TODO: split this up into a family of more specific errors? When playback
# failed partway into a redirect chain, when a redirect goes outside
# redirect_target_window, when a memento was circular?
class MementoPlaybackError(WaybackException):
    """
    Raised when a Memento can't be 'played back' (loaded) by the Wayback
    Machine for some reason. This is a server-side issue, not a problem in
    parsing data from Wayback.
    """


class WaybackRetryError(WaybackException):
    """
    Raised when a request to the Wayback Machine has been retried and failed
    too many times. The number of tries before this exception is raised
    generally depends on your `WaybackSession` settings.

    Attributes
    ----------
    retries : int
        The number of retries that were attempted.
    cause : Exception
        The actual, underlying error that would have caused a retry.
    time : int
        The total time spent across all retried requests, in seconds.
    """

    def __init__(self, retries, total_time, causal_error):
        self.retries = retries
        self.cause = causal_error
        self.time = total_time
        super().__init__(f'Retried {retries} times over {total_time or "?"} seconds (error: {causal_error})')


class RateLimitError(WaybackException):
    """
    Raised when the Wayback Machine responds with a 429 (too many requests)
    status code. In general, this package's built-in limits should help you
    avoid ever hitting this, but if you are running multiple processes in
    parallel, you could go overboard.

    Attributes
    ----------
    retry_after : int, optional
        Recommended number of seconds to wait before retrying. If the Wayback
        Machine does not include it in the HTTP response, it will be set to
        ``None``.
    """

    def __init__(self, response):
        self.response = response

        # The Wayback Machine does not generally include a `Retry-After` header
        # at the time of this writing, but this code is included in case they
        # add it in the future. The standard recommends it:
        # https://tools.ietf.org/html/rfc6585#section-4
        retry_header = response.headers.get('Retry-After')
        self.retry_after = int(retry_header) if retry_header else None

        message = 'Wayback rate limit exceeded'
        if self.retry_after:
            message = f'{message}, retry after {self.retry_after} s'

        super().__init__(message)


class SessionClosedError(Exception):
    """
    Raised when a Wayback session is used to make a request after it has been
    closed and disabled.
    """
