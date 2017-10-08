from pkg_resources import resource_filename
import pytest
import htmltreediff
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
def test_htmltreediff(fn):
    before, after = lookup_pair(fn)
    d = htmltreediff.diff(before, after, ins_tag='diffins', del_tag='diffdel',
                          pretty=True)
    print(TEMPLATE.format(before, after, d))


@pytest.mark.parametrize('fn', cases)
def test_html_diff_render(fn):
    before, after = lookup_pair(fn)
    d = html_diff_render(before, after)
    print(TEMPLATE.format(before, after, d))


@pytest.mark.parametrize('fn', cases)
def test_htmldiffer(fn):
    before, after = lookup_pair(fn)
    d = HTMLDiffer(before, after).combined_diff
    print(TEMPLATE.format(before, after, d))
