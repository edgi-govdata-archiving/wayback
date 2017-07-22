from bs4 import BeautifulSoup
import diff_match_patch
import re
import web_monitoring.pagefreezer
import sys


# BeautifulSoup can sometimes exceed the default Python recursion limit (1000).
sys.setrecursionlimit(10000)


def compare_length(a_body, b_body):
    "Compute difference in response body lengths. (Does not compare contents.)"
    return len(b_body) - len(a_body)


def identical_bytes(a_body, b_body):
    "Compute whether response bodies are exactly identical."
    return a_body == b_body


def _get_text(html):
    "Extract textual content from HTML."
    soup = BeautifulSoup(html, 'html.parser')
    return soup.findAll(text=True)


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
    return web_monitoring.pagefreezer.PageFreezer(a_url,b_url)


d = diff_match_patch.diff
d_b = diff_match_patch.diff_bytes

def html_text_diff(a_text, b_text):
    """
    Diff the visible textual content of an HTML document.

    Example
    ------
    >>> html_text_diff('<p>Deleted</p><p>Unchanged</p>',
    ...                '<p>Added</p><p>Unchanged</p>')
    [('-', 'Delet'), ('+', 'Add'), ('=', 'ed Unchanged')]
    """
    t1 = ' '.join(_get_visible_text(a_text))
    t2 = ' '.join(_get_visible_text(b_text))
    TIMELIMIT = 4  # seconds
    return d(t1, t2, checklines=False, timelimit=TIMELIMIT, cleanup_semantic=True, counts_only=False)


def html_source_diff(a_text, b_text):
    """
    Diff the full source code of an HTML document.

    Example
    ------
    >>> html_source_diff('<p>Deleted</p><p>Unchanged</p>',
    ...                  '<p>Added</p><p>Unchanged</p>')
    [(0, '<p>'), (-1, 'Delet'), (1, 'Add'), (0, 'ed</p><p>Unchanged</p>')]
    """
    TIMELIMIT = 4  # seconds
    return d_b(a_text.encode('utf-8'), b_text.encode('utf-8'), checklines=False, timelimit=TIMELIMIT, cleanup_semantic=True, counts_only=False)
