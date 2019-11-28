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
