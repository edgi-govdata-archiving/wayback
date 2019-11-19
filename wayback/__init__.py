from ._version import get_versions
__version__ = get_versions()['version']
del get_versions

from ._client import (  # noqa
    CdxRecord,
    memento_url_data,
    WaybackClient,
    WaybackSession)
