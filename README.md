# web-monitoring-processing

---
:information_source: **Welcome Mozilla Global Sprinters!** :wave: :tada: :confetti_ball:  
Thank you for helping out with our project, please take a moment to read our [Code of Conduct](https://github.com/edgi-govdata-archiving/overview/blob/master/CONDUCT.md) and project-specific [Contributing Guidelines](https://github.com/edgi-govdata-archiving/web-monitoring/blob/master/CONTRIBUTING.md).

:globe_with_meridians: We will be sprinting in-person at the [Toronto Mozilla Offices](https://ti.to/Mozilla/global-sprint-toronto), but remote contributors are more than welcome! Most of our team is based in the [Eastern Time Zone (ET)](https://en.wikipedia.org/wiki/Eastern_Time_Zone) or [Pacific Time Zone (PT)](https://en.wikipedia.org/wiki/Pacific_Time_Zone).

We are looking forward to working together! You can get started by:

- :speech_balloon: Joining the [Archivers Slack](https://archivers-slack.herokuapp.com/) and join `#dev` and `#dev-webmonitoring`
- :clipboard: Reviewing the [**web-monitoring**](https://github.com/edgi-govdata-archiving/web-monitoring) repo, in particular read about the [project architecture](https://github.com/edgi-govdata-archiving/web-monitoring#architecture)
- :bookmark_tabs: Looking at our issue tracker, for the global sprint we are targeting `mozsprint` or `first-timer` issues:

   | Repo | Issues |
   |------|--------|
   | [**web-monitoring**](https://github.com/edgi-govdata-archiving/web-monitoring) | [`mozsprint`](https://github.com/edgi-govdata-archiving/web-monitoring/issues?q=is%3Aissue+is%3Aopen+label%3Amozsprint), [`first-timer`](https://github.com/edgi-govdata-archiving/web-monitoring/issues?q=is%3Aissue+is%3Aopen+label%3Afirst-timer) |
   | [**web-monitoring-processing**](https://github.com/edgi-govdata-archiving/web-monitoring-processing) | [`mozsprint`](https://github.com/edgi-govdata-archiving/web-monitoring-processing/issues?q=is%3Aissue+is%3Aopen+label%3Amozsprint), [`first-timer`](https://github.com/edgi-govdata-archiving/web-monitoring-processing/issues?q=is%3Aissue+is%3Aopen+label%3Afirst-timer) |

---

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

* A Python API to PageFreezer's diffing service in
  ``web_monitoring.page_freezer``
* A Python API to the Internet Archive Wayback Machine's archived webpage
  snapshots in ``web_monitoring.internetarchive``
* A Python API to the web-monitoring-db Rails app in ``web_monitoring.db``
* A Python API to PageFreezer's archived snapshots in ``web_monitoring.pf_edgi``
* Python functions and a command-line tool for importing snapshots from PF and
  IA into web-monitoring-db.

Legacy projects that may be revisited:
* [Example HTML](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/archives) providing useful test cases.
* An experiment with the [newspaper
  module](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/get_article_text).

## Installation Instructions

1. Get Python 3.6. This packages makes use of modern Python features and
   requires Python 3.6+.  If you don't have Python 3.6, we recommend using
   [conda](https://conda.io/miniconda.html) to install it. (You don't need admin
   privileges to install or use it, and it won't interfere with any other
   installations of Python already on your system.)

2. Install the package.

    ```sh
    python setup.py develop
    ```

3. Copy the script `.env.example` to `.env` and supply any local configuration
   info you need. (Only some of the package's functionality requires this.)
   Apply the configuration:

    ```sh
    source .env
    ```
4. See module comments and docstrings for more usage information. There is
   currently no published documentation.
