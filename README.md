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

This component holds various backend tools serving different tasks:

1. Query external sources of captured web pages (e.g. Internet Archive, Page
   Freezer, Sentry), and formulate a request for importing their version and
   page metadata into web-monitoring-db.
2. Provide a web service that computes the "diff" between two versions of a page
   in response to a query from web-monitoring-db.
3. Query web-monitoring-db for new Changes, analyze them in an automated
   pipeline to assign priority and/or filter out uninteresting ones, and submit
   this information back to web-monitoring-db.

## Development status

Under active development:

* A tool for querying the Internet Archive and importing version and page
  metadata into web-monitoring-db.

Legacy projects that may be revisited:
* [Example HTML](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/archives) providing useful test cases.
* A [Python API to PageFreezer integrating with
  pandas](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/page_freezer_python_module)
  also demonstrated in a [Jupyter
  notebook](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/page_freezer_python_module/PageFreezer.ipynb).
* An experiment with the [newspaper
  module](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/get_article_text).

## Contribute

To contribute to this repository, please refer [DEVELOPER_DOCS.md](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/DEVELOPER_DOCS.md)
