import pytest
import web_monitoring.differs as wd


def test_side_by_side_text():
    actual = wd.side_by_side_text(a_text='<html><body>hi</body></html>',
                                  b_text='<html><body>bye</body></html>')
    expected = {'a_text': ['hi'], 'b_text': ['bye']}
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

def test_html_diff_render():
    text1 = '<!DOCTYPE html><html><head></head><body><p>Paragraph</p></body></html>'
    text2 = '<!DOCTYPE html><html><head></head><body><h1>Header</h1></body></html>'
    actual = html_diff_render(text1,text2)
    expected = '<!DOCTYPE html>\n<html>\n <style type="text/css">\n  ins {text-decoration : none; background-color: #d4fcbc;}\n                        del {text-decoration : none; background-color: #fbb6c2;}\n </style>\n <head></head>\n <body><h1><ins>Header</ins></h1> <p><del>Paragraph</del></p></body>\n</html>'
    assert actual == expected



def test_text_diff():
    actual = wd.html_text_diff('<p>Deleted</p><p>Unchanged</p>',
                               '<p>Added</p><p>Unchanged</p>')
    expected = [
                (-1, 'Delet'),
                (1, 'Add'),
                (0, 'ed Unchanged')]
    assert actual == expected


def test_html_diff():
    actual = wd.html_source_diff('<p>Deleted</p><p>Unchanged</p>',
                                 '<p>Added</p><p>Unchanged</p>')
    expected = [(0, '<p>'),
                (-1, 'Delet'),
                (1, 'Add'),
                (0, 'ed</p><p>Unchanged</p>')]
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
    expected = ['First Heading',
                'First paragraph.']
    assert actual == expected
