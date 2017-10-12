from distutils.core import setup
import glob
import os
from pathlib import Path
import setuptools
import sys

import versioneer


if sys.version_info < (3, 6):
    raise RuntimeError("Python version is {}. Requires 3.6 or greater."
                       "".format(sys.version_info))


def read(fname):
    with open(Path(__file__).parent / fname) as f:
        result = f.read()
    return result


# Requirements not on PyPI can't be installed through `install_requires`.
# They have to be installed manually or with `pip install -r requirements.txt`.
requirements = [r for r in read('requirements.txt').splitlines()
                if not r.startswith('git+https://')]


setup(name='web_monitoring',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      packages=['web_monitoring'],
      package_data={'web_monitoring': ['example_data/*',
                                       'web_monitoring/tests/cassettes/*']},
      scripts=glob.glob('scripts/*'),
      install_requires=requirements,
      long_description=read('README.md'),
     )
