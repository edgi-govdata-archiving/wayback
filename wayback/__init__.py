from ._version import get_versions
__version__ = get_versions()['version']
del get_versions

from ._client import (  # noqa
    original_url_for_memento,
    WaybackClient,
    WaybackSession)
