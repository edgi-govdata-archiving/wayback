"""
This module hosts tests for visual HTML diffs that check validity -- that is,
they focus on whether the diff will render properly or outputs correct/working
markup. Unlike the tests in `test_html_diff.py`, these tests can actually fail
in the sense that the diff is “wrong” as opposed to just testing that the diff
doesn’t break or throw exceptions.
"""

from pathlib import Path
from pkg_resources import resource_filename
import html5_parser
import pytest
import re
from web_monitoring.diff_errors import UndiffableContentError
from web_monitoring.html_diff_render import html_diff_render


# TODO: extend these to other html differs via parameterization, a la
# `test_html_diff.py`. Most of these are written generically enough they could
# feasibly work with any visual HTML diff routine.

def test_html_diff_render_works_on_pages_with_no_head():
    result = html_diff_render('<html><body>Hello</body></html>',
                              '<html><body>Goodbye</body></html>',
                              include='deletions')
    assert result


def test_html_diff_render_does_not_encode_embedded_content():
    html = '<script>console.log("uhoh");</script> ok ' \
           '<style>body {font-family: "arial";}</style>'
    result = html_diff_render(f'Hi! {html}', f'Bye {html}')['combined']
    assert '&quot;' not in result


def test_html_diff_render_doesnt_move_script_content_into_page_text():
    '''
    If the differ is actually diffing text across nodes and doesn't treat
    scripts specially, having a new script tag added after the original one
    (when the original one has changed content) can cause that start tag of the
    added script to get inserted inside the first script. Because it's embedded
    content, the close tag of the added script winds up closing the first
    script, and any deletions from the original script wind up being placed
    afterward, where they are no longer treated as script content.

    Confusing, I know. See test code below for example.

    Note this can occur with tag that embeds foreign content that is not parsed
    as part of the DOM (e.g. `<style>`).
    '''
    a = '''<div><script>var x = {json: 'old data};</script></div>'''
    b = '''<div><script>var x = {new: 'updated'};</script>
<script>var what = "totally new!";</script></div>'''

    # If this is broken, the output will look like:
    #   <div>
    #     <script>var x = <ins>{new: &#x27;updated&#x27;};<script>var what = &quot;totally new!&quot;;</script>
    #     <del>{json: 'old data};</del>
    #   </div>
    # Note how the deleted script code got extracted out into page text.
    result = html_diff_render(a, b)['combined']

    # if we remove scripts from the result we should have an empty <div>
    body = re.search(r'(?s)<body>(.*)</body>', result)[1]
    without_script = re.sub(r'(?s)<script[^>]*>.*?</script>', '', body)
    text_only = re.sub(r'<[^>]+>', '', without_script).strip()
    assert text_only == ''


def test_deactivate_deleted_active_elements():
    '''
    Method `_deactivate_deleted_active_elements` is used by `html_diff_render`
    internally to encapsulate `del > script` and `del > style` elements with a
    `<template class="wm-diff-deleted-inert">` tag. The result for each deleted
    tag should be like:

    <del class="wm-diff">
        <template class="wm-diff-deleted-inert">
            <script src="s2.js">
            </script>
        </template>
    </del>
    '''
    a = '''<body>
           <script src="s1.js"></script>
           <p>test</p>
           <script src="s2.js"></script></body>'''
    b = '''<body><p>test2</p></body>'''
    result = html_diff_render(a, b)['combined']
    soup = html5_parser.parse(result, treebuilder='soup', return_root=False)
    elements = soup.select('template.wm-diff-deleted-inert')
    assert len(elements) == 2


@pytest.mark.skip(reason='lxml parser does not support CDATA in html')
def test_html_diff_render_preserves_cdata_content():
    html = '<foo>A CDATA section: <![CDATA[ <hi>yes</hi> ]]> {}.</foo>'
    results = html_diff_render(html.format('old'), html.format('new'))
    result = results['combined']
    assert re.match(r'(&lt;hi&gt;)|(<!\[CDATA\[\s*<hi>)', result) is not None


def test_html_diff_render_should_count_changes():
    results = html_diff_render(
        'Here is some HTML that really has been <em>changed</em>.',
        'Here is some HTML; it really has definitely been <em>changed</em>!')

    assert isinstance(results['change_count'], int)
    assert isinstance(results['insertions_count'], int)
    assert isinstance(results['deletions_count'], int)
    assert results['change_count'] == results['insertions_count'] + results['deletions_count']


def test_html_diff_render_should_not_break_with_empty_content():
    results = html_diff_render(
        ' \n ',
        'Here is some actual content!')
    assert results


def test_html_diff_render_should_raise_for_non_html_content():
    pdf_file = resource_filename('web_monitoring', 'example_data/empty.pdf')
    pdf_content = Path(pdf_file).read_text(errors='ignore')

    with pytest.raises(UndiffableContentError):
        html_diff_render(
            '<p>Just a little HTML</p>',
            pdf_content)


def test_html_diff_render_should_check_content_type_header():
    with pytest.raises(UndiffableContentError):
        html_diff_render(
            '<p>Just a little HTML</p>',
            'Some other text',
            a_headers={'Content-Type': 'text/html'},
            b_headers={'Content-Type': 'image/jpeg'})


def test_html_diff_render_should_not_check_content_type_header_if_content_type_options_is_nocheck():
    html_diff_render(
        '<p>Just a little HTML</p>',
        'Some other text',
        a_headers={'Content-Type': 'text/html'},
        b_headers={'Content-Type': 'image/jpeg'},
        content_type_options='nocheck')


def test_html_diff_render_should_not_raise_for_non_html_content_if_content_type_options_is_nosniff():
    pdf_file = resource_filename('web_monitoring', 'example_data/empty.pdf')
    pdf_content = Path(pdf_file).read_text(errors='ignore')

    html_diff_render(
        '<p>Just a little HTML</p>',
        pdf_content,
        content_type_options='nosniff')


def test_html_diff_render_should_not_check_content_if_content_type_options_is_ignore():
    pdf_file = resource_filename('web_monitoring', 'example_data/empty.pdf')
    pdf_content = Path(pdf_file).read_text(errors='ignore')

    html_diff_render(
        '<p>Just a little HTML</p>',
        pdf_content,
        a_headers={'Content-Type': 'text/html'},
        b_headers={'Content-Type': 'application/pdf'},
        content_type_options='ignore')


def test_html_diff_works_on_documents_with_no_body():
    results = html_diff_render(
        '<!doctype html><html><head><title>Hi!</title></head></html>',
        '<!doctype html><html><head><title>Oops!</title></head></html>')

    assert 'combined' in results
    assert isinstance(results['combined'], str)
