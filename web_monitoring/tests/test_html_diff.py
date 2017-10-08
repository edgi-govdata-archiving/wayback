from pkg_resources import resource_filename
import pytest
import htmltreediff


def lookup_pair(fn):
    """Read example data named {fn}.before and {fn}.after"""
    fn1 = 'example_data/{}.before'.format(fn)
    fn2 = 'example_data/{}.after'.format(fn)
    with open(resource_filename('web_monitoring', fn1)) as f:
        before = f.read()
    with open(resource_filename('web_monitoring', fn2)) as f:
        after = f.read()
    return before, after


@pytest.mark.parametrize('fn',
                         ['change-tag',
                          'change-href',
                          'change-link-text',
                          'ins-in-source',
                          'two-paragraphs',
                          'add-paragraph',
                          'change-word-in-paragraph',
                         ])
def test_change(fn):
    # For now it's unclear what the 'expected' result should be, so this
    # test will never FAIL (but it can still ERROR). Run pytest with the -s
    # flag to see these outputs.
    before, after = lookup_pair(fn)
    d = htmltreediff.diff(before, after)
    print("""
BEFORE:
{}
AFTER:
{}
DIFF:
{}
""".format(before, after, d))
