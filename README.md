# web-monitoring-processing

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
