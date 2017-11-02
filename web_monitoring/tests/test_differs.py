import pytest
import re
import web_monitoring.differs as wd


def test_side_by_side_text():
    actual = wd.side_by_side_text(a_text='<html><body>hi</body></html>',
                                  b_text='<html><body>bye</body></html>')
    expected = {'a_text': 'hi', 'b_text': 'bye'}
    assert actual == expected


def test_compare_length():
    actual = wd.compare_length(a_body=b'asdf', b_body=b'asd')
    expected = -1
    assert actual == expected


def test_identical_bytes():
    actual = wd.identical_bytes(a_body=b'asdf', b_body=b'asdf')
    expected = True
    assert actual == expected

    actual = wd.identical_bytes(a_body=b'asdf', b_body=b'Asdf')
    expected = False
    assert actual == expected


def test_text_diff():
    actual = wd.html_text_diff('<p>Deleted</p><p>Unchanged</p>',
                               '<p>Added</p><p>Unchanged</p>')
    expected = [
                (-1, 'Delet'),
                (1, 'Add'),
                (0, 'ed Unchanged')]
    assert actual == expected


def test_text_diff_omits_more_than_two_consecutive_blank_lines():
    actual = wd.html_text_diff('''<p>Deleted</p>
                                  <script>whatever</script>
                                  <img src='something.jpg'>
                                  <p>Unchanged</p>''',
                               '''<p>Added</p>
                                  <script>some script</script>
                                  <img src='something.jpg'>
                                  <p>Unchanged</p>''')
    expected = [(-1, 'Delet'),
                (1, 'Add'),
                (0, 'ed\n\nUnchanged')]
    assert actual == expected


@pytest.mark.skip(reason="test not implemented")
def test_pagefreezer():
    # 1. Set up mock responses for calls to pagefreezer
    # actual = wd.pagefreezer('http://example.com/test_a',
    #                         'http://example.com/test_b')
    # 2. Ensure that the resulting output is properly passed through
    pass


def test_get_visible_text():
    html = '<!--First comment--><h1>First Heading</h1><p>First paragraph.</p>'
    actual = wd._get_visible_text(html)
    assert actual == 'First Heading First paragraph.'


# TODO: extend this to other html differs
# Should these move to `test_html_diff.py`? I kept them out of there because
# that file is mostly concerned with creating evaluatable output, not testing
# for correctness/validity like these are. These can actual FAIL.
def test_html_diff_render_does_not_encode_embedded_content():
    html = '<script>console.log("uhoh");</script> ok ' \
           '<style>body {font-family: "arial";}</style>'
    result = wd.html_diff_render(f'Hi! {html}', f'Bye {html}')
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
    result = wd.html_diff_render(a, b)

    # if we remove scripts from the result we should have an empty <div>
    body = re.search(r'(?s)<body>(.*)</body>', result)[1]
    without_script = re.sub(r'(?s)<script>.*?</script>', '', body)
    text_only = re.sub(r'<[^>]+>', '', without_script).strip()
    assert text_only == ''


@pytest.mark.skip(reason='lxml parser does not support CDATA in html')
def test_html_diff_render_preserves_cdata_content():
    html = '<foo>A CDATA section: <![CDATA[ <hi>yes</hi> ]]> {}.</foo>'
    result = wd.html_diff_render(html.format('old'), html.format('new'))
    assert re.match(r'(&lt;hi&gt;)|(<!\[CDATA\[\s*<hi>)', result) is not None
