from datetime import datetime
import functools
import htmltreediff
import time
import os
from pathlib import Path
from pkg_resources import resource_filename
import pytest
from web_monitoring.db import Client
from web_monitoring.differs import html_diff_render, insert_diff_style
from htmldiffer.diff import HTMLDiffer


def lookup_pair(fn):
    """Read example data named {fn}.before and {fn}.after"""
    fn1 = 'example_data/{}.before'.format(fn)
    fn2 = 'example_data/{}.after'.format(fn)
    with open(resource_filename('web_monitoring', fn1)) as f:
        before = f.read()
    with open(resource_filename('web_monitoring', fn2)) as f:
        after = f.read()
    return before, after


TEMPLATE = """
BEFORE:
{}
AFTER:
{}
DIFF:
{}
"""

cases = ['change-tag',
         'change-href',
         'change-link-text',
         'ins-in-source',
         'two-paragraphs',
         'add-paragraph',
         'change-word-in-paragraph',
         'change-title',
        ]

# For now it's unclear what the 'expected' results should be, so these
# tests will never FAIL (but it can still ERROR). Run pytest with the -s
# flag to see these outputs.

@pytest.mark.parametrize('fn', cases)
def test_contrived_examples_htmltreediff(fn):
    before, after = lookup_pair(fn)
    d = htmltreediff.diff(before, after, ins_tag='diffins', del_tag='diffdel',
                          pretty=True)
    print(TEMPLATE.format(before, after, d))


@pytest.mark.parametrize('fn', cases)
def test_contrived_examples_html_diff_render(fn):
    before, after = lookup_pair(fn)
    d = html_diff_render(before, after)
    print(TEMPLATE.format(before, after, d))


@pytest.mark.parametrize('fn', cases)
def test_contrived_examples_htmldiffer(fn):
    before, after = lookup_pair(fn)
    d = HTMLDiffer(before, after).combined_diff
    print(TEMPLATE.format(before, after, d))


### TESTS ON MORE COMPLEX, REAL CASES

staging_version_ids = [
    # @Mr0grog: "The “Survivor Impacts” text is in a `<p>` element between
    # two `<ul>` elements on this page, but in the diff, the `<p>` gets moved
    # _into_ the `<ul>`, so it renders like a list item instead of like the
    # header-ish thing it actually is."
     ('f2d5d701-707a-42e0-8881-653346d01e0a',
      'fc74d750-c651-46b7-bf74-434ad8c62e04'),
     # See issue #99
     ('9d4de183-a186-456c-bffb-55d82989877d',
      '775a8b04-9bac-4d0d-8db0-a8e133c4a964'),
    ]

# Fetch content as we need it, and cache. This can potentially matter if a
# subset of the tests are run.
version_content_cache = {}
staging_cli = Client(
    email=os.environ['WEB_MONITORING_DB_STAGING_EMAIL'],
    password=os.environ['WEB_MONITORING_DB_STAGING_PASSWORD'],
    url=os.environ['WEB_MONITORING_DB_STAGING_URL'])


CACHE_DIR = Path.home() / Path('cache', 'web-monitoring-processings', 'tests')
os.makedirs(CACHE_DIR, exist_ok=True)


def get_staging_content(version_id):
    # Try our local cache, the on-disk cache, and finally the network.
    try:
        return version_content_cache[version_id]
    except KeyError:
        try:
            with open(CACHE_DIR / Path(version_id), 'r') as f:
                content = f.read()
        except FileNotFoundError:
            content = staging_cli.get_version_content(version_id)
            with open(CACHE_DIR / Path(version_id), 'w') as f:
                f.write(content)
        version_content_cache[version_id] = content
        return content

OUTPUT_DIR = Path('diff_output_{}'.format(datetime.now().isoformat()))
os.makedirs(OUTPUT_DIR, exist_ok=True)


def export(func):
    @functools.wraps(func)
    def inner(*args, **kwargs):
        d = func(*args, **kwargs)
        with open(OUTPUT_DIR / Path(func.__name__), 'w') as file:
            file.write(d)
        return d
    return inner


@export
@pytest.mark.parametrize('before_id, after_id', staging_version_ids)
def test_real_examples_htmltreediff(before_id, after_id):
    before, after = map(get_staging_content, (before_id, after_id))
    d = htmltreediff.diff(before, after,
                          ins_tag='diffins',del_tag='diffdel',
                          pretty=True)
    d = insert_diff_style(d, 'diffins', 'diffdel')
    return d


@export
@pytest.mark.parametrize('before_id, after_id', staging_version_ids)
def test_real_examples_html_diff_render(before_id, after_id):
    before, after = map(get_staging_content, (before_id, after_id))
    d = html_diff_render(before, after)
    return d


@export
@pytest.mark.parametrize('before_id, after_id', staging_version_ids)
def test_real_examples_htmldiffer(before_id, after_id):
    before, after = map(get_staging_content, (before_id, after_id))
    d = HTMLDiffer(before, after).combined_diff
    d = insert_diff_style(d, 'ins', 'del')
    return d
