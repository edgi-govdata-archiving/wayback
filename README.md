[![Code of Conduct](https://img.shields.io/badge/%E2%9D%A4-code%20of%20conduct-blue.svg?style=flat)](https://github.com/edgi-govdata-archiving/overview/blob/master/CONDUCT.md)

# web-monitoring-processing

A component of the EDGI [Web Monitoring Project](https://github.com/edgi-govdata-archiving/web-monitoring).

## Overview of this component's tasks

This component is intended to hold various backend tools serving different tasks:

1. Query external sources of captured web pages (e.g. Internet Archive, Page
   Freezer, Sentry), and formulate a request for importing their version and
   page metadata into web-monitoring-db.
2. Provide a web service that computes the "diff" between two versions of a page
   in response to a query from web-monitoring-db.
3. Query web-monitoring-db for new Changes, analyze them in an automated
   pipeline to assign priority and/or filter out uninteresting ones, and submit
   this information back to web-monitoring-db.

## Development status

Working and Under Active Development:

* A Python API to the Internet Archive Wayback Machine's archived webpage
  snapshots in ``web_monitoring.internetarchive``
* A Python API to the web-monitoring-db Rails app in ``web_monitoring.db``
* Python functions and a command-line tool for importing snapshots from the
  Internet Archive into web-monitoring-db.
* An HTTP API for diffing two documents according to a variety of algorithms.
  (Uses the Tornado web framework.)

Legacy projects that may be revisited:
* [Example HTML](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/archives) providing useful test cases.

## Installation Instructions

1. Get Python 3.6. This packages makes use of modern Python features and
   requires Python 3.6+.  If you don't have Python 3.6, we recommend using
   [conda](https://conda.io/miniconda.html) to install it. (You don't need admin
   privileges to install or use it, and it won't interfere with any other
   installations of Python already on your system.)

2. Install the package.

    ```sh
    pip install -r requirements.txt
    python setup.py develop
    ```

3. Copy the script `.env.example` to `.env` and supply any local configuration
   info you need. (Only some of the package's functionality requires this.)
   Apply the configuration:

    ```sh
    source .env
    ```
4. See module comments and docstrings for more usage information. Also see the
   command line tool ``wm``, which is installed with the package. For help, use

   ```sh
   wm --help
   ```

5. To run the tests or build the documentation, first install the development
   requirements.

   ```sh
   pip install -r dev-requirements.txt
   ```

6. To build the docs:

   ```sh
   cd docs
   make html
   ```

7. To run the tests:

   ```sh
   python run_tests.py
   ```

   Any additional arguments are passed through to `py.test`.

## Docker

The Dockerfile runs ``wm-diffing-server`` on port 80 in the container. To build
and run:

```
docker build -t processing .
docker run -p 4000:80 processing
```

Point your browser or ``curl`` at ``http://localhost:4000``.

## Code of Conduct

This repository falls under EDGI's [Code of Conduct](https://github.com/edgi-govdata-archiving/overview/blob/master/CONDUCT.md).

## Contributors

This project wouldn’t exist without a lot of amazing people’s help. Thanks to the following for all their contributions! See our [contributing guidelines](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/CONTRIBUTING.md) to find out how you can help.

<!-- ALL-CONTRIBUTORS-LIST:START -->
| Contributions | Name |
| ----: | :---- |
| [💻](# "Code") [⚠️](# "Tests") [🚇](# "Infrastructure") [📖](# "Documentation") [💬](# "Answering Questions") [👀](# "Reviewer") | [Dan Allan](https://github.com/danielballan) |
| [💻](# "Code") | [Vangelis Banos](https://github.com/vbanos) |
| [💻](# "Code") [📖](# "Documentation") | [Chaitanya Prakash Bapat](https://github.com/ChaiBapchya) |
| [💻](# "Code") [⚠️](# "Tests") [🚇](# "Infrastructure") [📖](# "Documentation") [💬](# "Answering Questions") [👀](# "Reviewer") | [Rob Brackett](https://github.com/Mr0grog) |
| [💻](# "Code") | [Stephen Buckley](https://github.com/StephenAlanBuckley) |
| [💻](# "Code") [📖](# "Documentation") [📋](# "Organizer") | [Ray Cha](https://github.com/weatherpattern) |
| [💻](# "Code") [⚠️](# "Tests") | [Janak Raj Chadha](https://github.com/janakrajchadha) |
| [💻](# "Code") | [Autumn Coleman](https://github.com/AutumnColeman) |
| [💻](# "Code") | [Luming Hao](https://github.com/lh00000000) |
| [🤔](# "Ideas and Planning") | [Mike Hucka](https://github.com/mhucka) |
| [💻](# "Code") | [Stuart Lynn](https://github.com/stuartlynn) |
| [💻](# "Code") | [Allan Pichardo](https://github.com/allanpichardo) |
| [📖](# "Documentation") [📋](# "Organizer") | [Matt Price](https://github.com/titaniumbones) |
| [📖](# "Documentation") | [Susan Tan](https://github.com/ArcTanSusan) |
| [💻](# "Code") [⚠️](# "Tests") | [Fotis Tsalampounis](https://github.com/ftsalamp) |
| [📖](# "Documentation") [📋](# "Organizer") | [Dawn Walker](https://github.com/dcwalk) |
<!-- ALL-CONTRIBUTORS-LIST:END -->

(For a key to the contribution emoji or more info on this format, check out [“All Contributors.”](https://github.com/kentcdodds/all-contributors))


## License & Copyright

Copyright (C) 2017-2018 Environmental Data and Governance Initiative (EDGI)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 3.0.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

See the [`LICENSE`](https://github.com/edgi-govdata-archiving/webpage-versions-processing/blob/master/LICENSE) file for details.
