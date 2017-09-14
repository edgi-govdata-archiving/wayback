from bs4 import BeautifulSoup, Comment
from diff_match_patch import diff, diff_bytes
from lxml.html.diff import htmldiff
import re
import web_monitoring.pagefreezer
import sys
import os

# BeautifulSoup can sometimes exceed the default Python recursion limit (1000).
sys.setrecursionlimit(10000)

# Dictionary mapping which maps from diff-match-patch tags to the ones we use
diff_codes = {'=': 0, '-': -1, '+': 1}

def compare_length(a_body, b_body):
    "Compute difference in response body lengths. (Does not compare contents.)"
    return len(b_body) - len(a_body)


def identical_bytes(a_body, b_body):
    "Compute whether response bodies are exactly identical."
    return a_body == b_body


def _get_text(html):
    "Extract textual content from HTML."
    soup = BeautifulSoup(html, 'lxml')
    [element.extract() for element in
     soup.find_all(string=lambda text:isinstance(text, Comment))]
    return soup.find_all(text=True)


def _is_visible(element):
    "A best-effort guess at whether an HTML element is visible on the page."
    # adapted from https://www.quora.com/How-can-I-extract-only-text-data-from-HTML-pages
    INVISIBLE_TAGS = ('style', 'script', '[document]', 'head', 'title')
    if element.parent.name in INVISIBLE_TAGS:
        return False
    elif re.match('<!--.*-->', str(element.encode('utf-8'))):
        return False
    return True


def _get_visible_text(html):
    return list(filter(_is_visible, _get_text(html)))


def side_by_side_text(a_text, b_text):
    "Extract the visible text from both response bodies."
    return {'a_text': _get_visible_text(a_text),
            'b_text': _get_visible_text(b_text)}


def pagefreezer(a_url, b_url):
    "Dispatch to PageFreezer."
    # Just send PF the urls, not the whole body.
    # It is still useful that we downloaded the body because we are able to
    # validate it against the expected hash.
    obj = web_monitoring.pagefreezer.PageFreezer(a_url, b_url)
    return obj.query_result

def compute_dmp_diff(a_text, b_text, timelimit=4):

    if (isinstance(a_text, str) and isinstance(b_text, str)):
        changes = diff(a_text, b_text, checklines=False, timelimit=timelimit, cleanup_semantic=True, counts_only=False)
    elif (isinstance(a_text, bytes) and isinstance(b_text, bytes)):
        changes = diff_bytes(a_text, b_text, checklines=False, timelimit=timelimit, cleanup_semantic=True, counts_only=False)
    else:
        raise TypeError("Both the texts should be either of type 'str' or 'bytes'.")

    result = [(diff_codes[change[0]], change[1]) for change in changes]
    return result

def html_text_diff(a_text, b_text):
    """
    Diff the visible textual content of an HTML document.

    Example
    ------
    >>> html_text_diff('<p>Deleted</p><p>Unchanged</p>',
    ...                '<p>Added</p><p>Unchanged</p>')
    [[-1, 'Delet'], [1, 'Add'], [0, 'ed Unchanged']]
    """

    t1 = ' '.join(_get_visible_text(a_text))
    t2 = ' '.join(_get_visible_text(b_text))

    TIMELIMIT = 2 #seconds
    return compute_dmp_diff(t1, t2, timelimit=TIMELIMIT)

def html_source_diff(a_text, b_text):
    """
    Diff the full source code of an HTML document.

    Example
    ------
    >>> html_source_diff('<p>Deleted</p><p>Unchanged</p>',
    ...                  '<p>Added</p><p>Unchanged</p>')
    [[0, '<p>'], [-1, 'Delet'], [1, 'Add'], [0, 'ed</p><p>Unchanged</p>']]
    """
    TIMELIMIT = 2 #seconds
    return compute_dmp_diff(a_text, b_text, timelimit=TIMELIMIT)

def html_diff_render(a_text, b_text):
    """
    HTML Diff for rendering

    Example
    -------
    text1 = '<!DOCTYPE html><html><head></head><body><p>Paragraph</p></body></html>'
    text2 = '<!DOCTYPE html><html><head></head><body><h1>Header</h1></body></html>'
    test_diff_render = html_diff_render(text1,text2)
    """
    soup_old = BeautifulSoup(a_text, 'lxml')
    soup_new = BeautifulSoup(b_text, 'lxml')

    [element.extract() for element in
     soup_old.find_all(string=lambda text:isinstance(text, Comment))]
    [element.extract() for element in
     soup_new.find_all(string=lambda text:isinstance(text, Comment))]

    old_content = [str(child) for child in soup_old.html.children]
    new_content = [str(child) for child in soup_new.html.children]

    parent_tags = [content[:content.find('>')+1] for content in new_content]
    parent_tag_names = [tag[1:tag.find(' ')] + '>' if (tag.find(' ') != -1) else tag[1:] for tag in parent_tags]

    diff_list = []
    for index in range(len(new_content)):
        diff_list.append(htmldiff(old_content[index], new_content[index]))

    diff_list = [os.linesep.join([s for s in text.splitlines() if s]) for text in diff_list]

    append_list = [parent_tags[index]+diff_list[index]+'</'+parent_tag_names[index] for index in range(len(new_content))]

    soup_new.html.clear()

    new_tag = soup_new.new_tag("style", type="text/css")
    new_tag.string = """ins {text-decoration : none; background-color: #d4fcbc;}
                        del {text-decoration : none; background-color: #fbb6c2;}"""
    soup_new.html.append(new_tag)

    for index in range(len(append_list)):
        soup_new.html.append(append_list[index])

    render = soup_new.prettify(formatter=None)

    return render
