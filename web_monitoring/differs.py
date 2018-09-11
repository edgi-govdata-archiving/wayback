from bs4 import BeautifulSoup, Comment
from diff_match_patch import diff, diff_bytes
from htmldiffer.diff import HTMLDiffer
import htmltreediff
import os
import re
import sys
import web_monitoring.pagefreezer

# BeautifulSoup can sometimes exceed the default Python recursion limit (1000).
sys.setrecursionlimit(10000)

# Dictionary mapping which maps from diff-match-patch tags to the ones we use
diff_codes = {'=': 0, '-': -1, '+': 1}

REPEATED_BLANK_LINES = re.compile(r'([^\S\n]*\n\s*){2,}')


def compare_length(a_body, b_body):
    "Compute difference in response body lengths. (Does not compare contents.)"
    return {'diff': len(b_body) - len(a_body)}


def identical_bytes(a_body, b_body):
    "Compute whether response bodies are exactly identical."
    return {'diff': a_body == b_body}


def _get_text(html):
    "Extract textual content from HTML."
    soup = BeautifulSoup(html, 'lxml')
    [element.extract() for element in
     soup.find_all(string=lambda text: isinstance(text, Comment))]
    return soup.find_all(text=True)


INVISIBLE_TAGS = set(['style', 'script', '[document]', 'head', 'title'])
_RE_HTML_COMMENT = re.compile('<!--.*-->')


def _is_visible(element):
    "A best-effort guess at whether an HTML element is visible on the page."
    # adapted from https://www.quora.com/How-can-I-extract-only-text-data-from-HTML-pages
    if element.parent.name in INVISIBLE_TAGS:
        return False
    elif _RE_HTML_COMMENT.match(str(element.encode('utf-8'))):
        return False
    return True


def _get_visible_text(html):
    text = ' '.join(filter(_is_visible, _get_text(html)))
    return REPEATED_BLANK_LINES.sub('\n\n', text).strip()


def side_by_side_text(a_text, b_text):
    "Extract the visible text from both response bodies."
    return {'diff': {'a_text': _get_visible_text(a_text),
                     'b_text': _get_visible_text(b_text)}}


def pagefreezer(a_url, b_url):
    "Dispatch to PageFreezer."
    # Just send PF the urls, not the whole body.
    # It is still useful that we downloaded the body because we are able to
    # validate it against the expected hash.
    obj = web_monitoring.pagefreezer.PageFreezer(a_url, b_url)
    return {'diff': obj.query_result}


def compute_dmp_diff(a_text, b_text, timelimit=4):
    if (isinstance(a_text, str) and isinstance(b_text, str)):
        changes = diff(a_text, b_text, checklines=False, timelimit=timelimit, cleanup_semantic=True, counts_only=False)
    elif (isinstance(a_text, bytes) and isinstance(b_text, bytes)):
        changes = diff_bytes(a_text, b_text, checklines=False, timelimit=timelimit, cleanup_semantic=True,
                             counts_only=False)
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

    t1 = _get_visible_text(a_text)
    t2 = _get_visible_text(b_text)

    TIMELIMIT = 2  # seconds
    res = compute_dmp_diff(t1, t2, timelimit=TIMELIMIT)
    count = len([[type_, string_] for type_, string_ in res if type_])
    return {'change_count': count, 'diff': res}


def html_source_diff(a_text, b_text):
    """
    Diff the full source code of an HTML document.

    Example
    ------
    >>> html_source_diff('<p>Deleted</p><p>Unchanged</p>',
    ...                  '<p>Added</p><p>Unchanged</p>')
    [[0, '<p>'], [-1, 'Delet'], [1, 'Add'], [0, 'ed</p><p>Unchanged</p>']]
    """
    TIMELIMIT = 2  # seconds
    res = compute_dmp_diff(a_text, b_text, timelimit=TIMELIMIT)
    count = len([[type_, string_] for type_, string_ in res if type_])
    return {'change_count': count, 'diff': res}


def insert_style(html, css):
    """
    Insert a new <style> tag with CSS.

    Parameters
    ----------
    html : string
    css : string

    Returns
    -------
    render : string
    """
    soup = BeautifulSoup(html, 'lxml')

    # Ensure html includes a <head></head>.
    if not soup.head:
        head = soup.new_tag('head')
        soup.html.insert(0, head)

    style_tag = soup.new_tag("style", type="text/css")
    style_tag.string = css
    soup.head.append(style_tag)
    render = soup.prettify(formatter=None)
    return render


def html_tree_diff(a_text, b_text):
    differ_insertion = os.environ.get('DIFFER_INSERTION')
    if differ_insertion is None or differ_insertion == '':
        differ_insertion = '#d4fcbc'
    differ_deletion = os.environ.get('DIFFER_DELETION')
    if differ_deletion is None or differ_deletion == '':
        differ_deletion = '#fbb6c2'
    css = """
diffins {text-decoration : none; background-color: %s;}
diffdel {text-decoration : none; background-color: %s;}
diffins * {text-decoration : none; background-color: %s;}
diffdel * {text-decoration : none; background-color: %s;}
    """ % (differ_insertion, differ_deletion, differ_insertion,
           differ_deletion)
    d = htmltreediff.diff(a_text, b_text,
                          ins_tag='diffins', del_tag='diffdel',
                          pretty=True)
    # TODO Count number of changes.
    return {'diff': insert_style(d, css)}


def html_differ(a_text, b_text):
    differ_insertion = os.environ.get('DIFFER_INSERTION')
    if differ_insertion is None or differ_insertion == '':
        differ_insertion = '#d4fcbc'
    differ_deletion = os.environ.get('DIFFER_DELETION')
    if differ_deletion is None or differ_deletion == '':
        differ_deletion = '#fbb6c2'
    css = """
.htmldiffer_insert {text-decoration : none; background-color: %s;}
.htmldiffer_delete {text-decoration : none; background-color: %s;}
.htmldiffer_insert * {text-decoration : none; background-color: %s;}
.htmldiffer_delete * {text-decoration : none; background-color: %s;}
    """ % (differ_insertion, differ_deletion, differ_insertion,
           differ_deletion)
    d = HTMLDiffer(a_text, b_text).combined_diff
    # TODO Count number of changes.
    return {'diff': insert_style(d, css)}
