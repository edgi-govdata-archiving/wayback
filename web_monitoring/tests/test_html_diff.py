from pkg_resources import resource_filename
import pytest
import htmltreediff
from web_monitoring.db import fetch_version_content
from web_monitoring.differs import html_diff_render
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

# TODO These UUIDs refer to the staging app and therefore assume that the
# env variable WEB_MONITORING_DB_URL is pointed at staging.
version_ids = [
     ('f2d5d701-707a-42e0-8881-653346d01e0a',
      'fc74d750-c651-46b7-bf74-434ad8c62e04'),
    ]

# Fetch content as we need it, and cache. This can potentially matter if a
# subset of the tests are run.
version_content_cache = {}

def get_content(version_id):
    try:
        return version_content_cache[version_id]
    except KeyError:
        content = fetch_version_content(version_id).decode()
        version_content_cache[version_id] = content
        return content


@pytest.mark.parametrize('before_id, after_id', version_ids)
def test_real_examples_htmltreediff(before_id, after_id):
    before, after = get_content(before_id), get_content(after_id)
    htmltreediff.diff(before, after,
                      ins_tag='diffins',del_tag='diffdel',
                      pretty=True)


@pytest.mark.parametrize('before_id, after_id', version_ids)
def test_real_examples_html_diff_render(before_id, after_id):
    before, after = get_content(before_id), get_content(after_id)
    html_diff_render(before, after)


@pytest.mark.parametrize('before_id, after_id', version_ids)
def test_real_examples_htmldiffer(before_id, after_id):
    before, after = get_content(before_id), get_content(after_id)
    HTMLDiffer(before, after).combined_diff
