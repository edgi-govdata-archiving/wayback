import logging
import os
from ._version import get_versions
__version__ = get_versions()['version']
del get_versions


if os.environ.get('LOG_LEVEL'):
    logging.basicConfig(level=os.environ['LOG_LEVEL'].upper())
