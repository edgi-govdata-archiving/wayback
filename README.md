# web-monitoring-processing

## Architecture of the web-monitoring project

* [web-monitoring-db](https://github.com/edgi-govdata-archiving/web-monitoring-db), a Rails app (in development) for serving diffs and collecting human-entered annotations
* [web-monitoring-ui](https://github.com/edgi-govdata-archiving/web-monitoring-ui), font-end code that will communicate with the Rails app via JSON
* This repo, web-monitoring-processing, populates a database of processed diffs
  to be served by the Rails app.

## Overview of the task

1. Ingest a cache of captured HTML files, representing a Page as a series of
   Snapshots through time.
2. Compare Snapshots of the same Page by sending requests to PageFreezer (or
   some other service). Store the respones (Diffs).
3. Assign Priorities to the Diffs and provide the prioritized Diffs to the Rails
   app in web-monitoring-db.
4. Receive Annotations from the Rails app and incorporate these in future
   prioritization.

## Development status

This repo contains:

* [Example HTML](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/archives) providing useful test cases.
* A draft [database schema](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/web_monitoring/db.py#L30) with a Python API, demonstrated in [a Jupyter notebook](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/backend-demo.ipynb).
  This targets PageFrezer, whereas web-monitoring-db targets Versionista. The
  goal is to store both and provide a common interface to Diffs.
* A [Python API to PageFreezer integrating with
  pandas](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/page_freezer_python_module)
  also demonstrated in a [Jupyter
  notebook](https://github.com/edgi-govdata-archiving/web-monitoring-processing/blob/master/page_freezer_python_module/PageFreezer.ipynb).
* An experiment with the [newspaper
  module](https://github.com/edgi-govdata-archiving/web-monitoring-processing/tree/master/get_article_text).
