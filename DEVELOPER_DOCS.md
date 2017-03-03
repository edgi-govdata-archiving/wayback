# Developer Documentaiton

## Story

An admin provides some initial data to the server:

* An admin registers Pages (URLs) to be tracked, with associated agency
  metadata.
* At some point, a new file dump of captured HTML pages becomes available in
  storage. An admin registers these new Snapshots. A Snapshot refers to a Page
  and a time of capture, along with the location of the captured HTML in
  storage.

In the background, the backend processes new Snapshots:

* The backend requests a diff from PageFreezer (or some similar API) between the
  Snapshot and some ancestor Snapshot of the same Page. (It could be the oldest,
  or the most recent, or any between --- no assumptions are built in.)
* The backend stashes PageFreezer's response along with a hash of the diff, which
  can be used to identify unique diff and related identical ones.
* Then, each unique diff is assigned a priority. To start, this prority may
  simply be 1 (probably interesting) or 0 (probably not interesting).

When a user shows up:

* User logs into the Rails app. Their identity may be associated with a certain
  subdomain or area of expertise, as designated by an admin.
* User requests the "next" diffs to evaluate and get a table of the
  highest-priority diffs in their area.
* Server determines the highest priority diff that needs human inspection and
  redirects user to ``/diff/<DIFF_HASH>``. This is a permanent link that can be
  shared or revisited later.
* The page at ``/diff/<DIFF_HASH>`` displays viral statistics about the diff,
  gleaned from PageFreezer's result object, including text-only changes and
  source changes.
* Meanwhile, a visual diff is loaded asynchronously on the client side.
* The user enters their evaluation of the diff. This information, dubbed an
  Annotation, is stored separately from the Diff. One Diff can potentially
  be annotated by multiple people.
* The process repeats with the next diff in the priority queue.

## Components

* A SQL database which contains:
    * Pages: associates a URL with agency metadata
    * Snapshots: assocates an HTML snapshot at a specific time with a Page
    * Diffs: stores a reference to a PageFreezer (or PageFreezer-like) result
      for a diff of two Snapshots along with a hash of that diff
    * Priorities: associates each Diff with a priority ranking
    * Annotations: Human-entered information about a Diff
* A server written in Python using the Tornado framework.
* A frontend using TypeScript, JQuery, and Bootstrap.

## Development Install

Create a new postgresql user and database.
```
createuser web_monitoring --pwprompt  # Enter a password.
createdb -O web_monitoring web_monitoring_dev
export WEB_VERSIONING_SQL_DB_URI="postgresql://web_monitoring:<PASSWORD>@localhost/web_monitoring_dev"
```

Install Python package.

```
pip install -r requirements.txt
python setup.py develop
```

Experiment interactively with the backend. For example, using IPython:

```
ipython -i web_monitoring/interactive.py
```

```python
load_examples()  # Load examples in archives/ into Pages and Snapshots.
diff_new_snapshots()  # Process all Snapshots using PageFreezer (takes ~30 secs)
# This part still needs a nice dev API, but you can grab a Diff like this:
diffs[diffs._engine.execute(diffs._table.select()).fetchone().uuid]
```
