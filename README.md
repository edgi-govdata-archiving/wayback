# web-monitoring-processing

This is a component of the
[web-monitoring project](https://github.com/edgi-govdata-archiving/web-monitoring).

## Overview of this component's task

1. Ingest a cache of captured HTML files, representing a Page as a series of
   Snapshots through time.
2. Compare Snapshots of the same Page by sending requests to PageFreezer (or
   some other service). Store the responses (Diffs).
3. Assign Priorities to the Diffs and provide the prioritized Diffs to the Rails
   app in web-monitoring-db.
4. Receive Annotations from the Rails app and incorporate these in future
   prioritization.

## Sub-projects

See the GH issues for details but here's a quick overview.

* Refine the database schema for Pages, Snapshots, and Diffs, to be shared with
  the Rails app in web-monitoring-db.
* Build a tool for downloading captured HTML from Versionista and registering
  Snapshots.
* Do the same for the Internet Archive.
* Build a tool for parsing HTML dumps from PageFreezer and registering
  Snapshots.
* Analyze changes *within* a page and treat them separately instead of bluntly
  analyzing a whole page as an atomic unit.
* Apply text processing / ML to identify interesting changes and assign a
  numerical priority.
* Use information entered by volunteers to develop a smarter semantic differ
  (preferrably with the same inputs and outputs as PageFreezer's API).

## Development status

This repo contains:

* [Example HTML](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/archives) providing useful test cases.
* A draft [database schema](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/web_monitoring/db.py#L30) with a Python API, demonstrated in [a Jupyter notebook](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/backend-demo.ipynb).
  This targets PageFreezer, whereas web-monitoring-db targets Versionista. The
  goal is to store both and provide a common interface to Diffs.
* A [Python API to PageFreezer integrating with
  pandas](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/page_freezer_python_module)
  also demonstrated in a [Jupyter
  notebook](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/page_freezer_python_module/PageFreezer.ipynb).
* An experiment with the [newspaper
  module](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/get_article_text).
