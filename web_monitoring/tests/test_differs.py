import pytest
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
    assert actual == 'First Heading First paragraph.'


def test_html_diff_render():
    test_data = [('<html><head></head><body><p>Paragraph</p></body></html>',
                  '<html><head></head><body><h1>Heading</h1></body></html>'),
                 ('<html><body><p>Paragraph</p></body></html>',
                  '<html><body><h1>Heading</h1><p>Paragraph</p></html>'),
                 ('<html><body><p>Paragraph</p></body></html>',
                  '<html><body><h3>Paragraph</h3></body></html>'),
                 ('<html><head><title>HTML Diff Render</title></head><body><h1>Heading</h1></body></html>',
                  '<html><head><title>HTML Difference Render</title></head><body><h1>Head</h1></body></html>')]

    test_results = ['<html>\n <head>\n  <style type="text/css">\n   ins {text-decoration : none; background-color: #d4fcbc;}\n                        del {text-decoration : none; background-color: #fbb6c2;}\n  </style>\n </head> <body>\n  <h1><ins>Heading</ins></h1> <p><del>Paragraph</del></p>\n </body>\n</html>',
                    '<html>\n <head>\n  <style type="text/css">\n   ins {text-decoration : none; background-color: #d4fcbc;}\n                        del {text-decoration : none; background-color: #fbb6c2;}\n  </style>\n </head> <body>\n  <h1><ins>Heading</ins></h1> <p>Paragraph</p>\n </body>\n</html>',
                    '<html>\n <head>\n  <style type="text/css">\n   ins {text-decoration : none; background-color: #d4fcbc;}\n                        del {text-decoration : none; background-color: #fbb6c2;}\n  </style>\n </head> <body>\n  <h3>Paragraph</h3>\n </body>\n</html>',
                    '<html>\n <head>\n  <title>HTML <ins>Difference</ins> <del>Diff</del> Render</title>\n  <style type="text/css">\n   ins {text-decoration : none; background-color: #d4fcbc;}\n                        del {text-decoration : none; background-color: #fbb6c2;}\n  </style>\n </head> <body>\n  <h1><ins>Head</ins></h1> <h1><del>Heading</del></h1>\n </body>\n</html>']

    for index in range(len(test_data)):
        diff = wd.html_diff_render(test_data[index][0], test_data[index][1])
        assert (f'{index}: ' + test_results[index]) == (f'{index}: ' + diff)


def test_html_diff_render_handles_differing_numbers_of_nodes():
    test_data = ('<html><head></head><body><p>Paragraph</p></body></html>',
                 '<html><head></head>\n<body><h1>Heading</h1></body></html>')

    expected = '<html>\n <head>\n  <style type="text/css">\n   ins {text-decoration : none; background-color: #d4fcbc;}\n                        del {text-decoration : none; background-color: #fbb6c2;}\n  </style>\n </head> <body>\n  <h1><ins>Heading</ins></h1> <p><del>Paragraph</del></p>\n </body>\n</html>'
    diff = wd.html_diff_render(test_data[0], test_data[1])
    assert expected == diff
