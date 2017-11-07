from bs4 import BeautifulSoup, Comment
import copy
from diff_match_patch import diff, diff_bytes
from htmldiffer.diff import HTMLDiffer
import htmltreediff
from lxml.html.diff import (tokenize, htmldiff_tokens, fixup_ins_del_tags,
                            href_token)
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
    text = ' '.join(filter(_is_visible, _get_text(html)))
    return REPEATED_BLANK_LINES.sub('\n\n', text).strip()


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

    t1 = _get_visible_text(a_text)
    t2 = _get_visible_text(b_text)

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
    HTML Diff for rendering. This is focused on visually highlighting portions
    of a page’s text that have been changed. It does not do much to show how
    node types or attributes have been modified (save for link or image URLs).

    The overall page returned primarily represents the structure of the "new"
    or "B" version. However, it contains some useful metadata in the `<head>`:

    1. A `<template id="wm-diff-old-head">` contains the contents of the "old"
       or "A" version’s `<head>`.
    2. A `<style id="wm-diff-style">` contains styling diff-specific styling.
    3. A `<meta name="wm-diff-title" content="[diff]">` contains a renderable
       HTML diff of the page’s `<title>`. For example:

        `The <del>old</del><ins>new</ins> title`

    NOTE: you may want to be careful with rendering this response as-is;
    inline `<script>` and `<style>` elements may be included twice if they had
    changes, which could have undesirable runtime effects.

    Example
    -------
    text1 = '<!DOCTYPE html><html><head></head><body><p>Paragraph</p></body></html>'
    text2 = '<!DOCTYPE html><html><head></head><body><h1>Header</h1></body></html>'
    test_diff_render = html_diff_render(text1,text2)
    """
    soup_old = BeautifulSoup(a_text, 'lxml')
    soup_new = BeautifulSoup(b_text, 'lxml')

    # Remove comment nodes since they generally don't affect display.
    # NOTE: This could affect display if the removed are conditional comments,
    # but it's unclear how we'd meaningfully visualize those anyway.
    [element.extract() for element in
     soup_old.find_all(string=lambda text:isinstance(text, Comment))]
    [element.extract() for element in
     soup_new.find_all(string=lambda text:isinstance(text, Comment))]

    # Ensure the new soup (which we will modify and return) has a `<head>`
    if not soup_new.head:
        head = soup_new.new_tag('head')
        soup_new.html.insert(0, head)

    # htmldiff will unfortunately try to diff the content of elements like
    # <script> or <style> that embed foreign cnontent that shouldn't be parsed
    # as part of the DOM. We work around this by replacing those elements
    # with placeholders, but a better upstream fix would be to have
    # `flatten_el()` handle these cases by creating a special token, e.g:
    #
    #  class undiffable_tag(token):
    #    def __new__(cls, html_repr, **kwargs):
    #      # Make the value this represents for diffing an empty string
    #      obj = token.__new__(cls, '', **kwargs)
    #      # But keep the actual source around for serializing when done
    #      obj.html_repr = html_repr
    #
    #    def html(obj):
    #      return self.html_repr
    soup_old, replacements_old = _remove_undiffable_content(soup_old, 'old')
    soup_new, replacements_new = _remove_undiffable_content(soup_new, 'new')

    # htmldiff primarily diffs just *readable text*, so it doesn't really
    # diff parts of the page outside the `<body>` (e.g. `<head>`). We don't
    # have a great way to visualize metadata changes anyway.
    soup_new.body.replace_with(_diff_elements(soup_old.body, soup_new.body))

    # The `name` keyword sets the node name, not the `name` attribute
    title_meta = soup_new.new_tag(
        'meta',
        content=_diff_title(soup_old, soup_new))
    title_meta.attrs['name'] = 'wm-diff-title'
    soup_new.head.append(title_meta)

    old_head = soup_new.new_tag('template', id='wm-diff-old-head')
    if soup_old.head:
        for node in soup_old.head.contents.copy():
            old_head.append(node)
    soup_new.head.append(old_head)

    change_styles = soup_new.new_tag(
        "style",
        type="text/css",
        id='wm-diff-style')
    change_styles.string = """ins {text-decoration : none; background-color: #d4fcbc;}
                        del {text-decoration : none; background-color: #fbb6c2;}"""
    soup_new.head.append(change_styles)

    # The method we use above to append HTML strings (the diffs) to the soup
    # results in a non-navigable soup. So we serialize and re-parse :(
    # (Note we use no formatter for this because proper encoding escape the
    # tags our differ generated.)
    soup_new = BeautifulSoup(soup_new.prettify(formatter=None), 'lxml')
    replacements_new.update(replacements_old)
    soup_new = _add_undiffable_content(soup_new, replacements_new)

    return soup_new.prettify(formatter='minimal')


def _remove_undiffable_content(soup, prefix=''):
    """
    Find nodes that cannot be diffed (e.g. <script>, <style>) and replace them
    with an empty node that has the attribute `wm-diff-replacement="some ID"`

    Returns a tuple of the cleaned-up soup and a dict of replacements.
    """
    replacements = {}

    # NOTE: we may want to consider treating <object> and <canvas> similarly.
    # (They are "transparent" -- containing DOM, but only as a fallback.)
    for index, element in enumerate(soup.find_all(['script', 'style'])):
        replacement_id = f'{prefix}-{index}'
        replacements[replacement_id] = element
        replacement = soup.new_tag(element.name, **{
            'wm-diff-replacement': replacement_id
        })
        # The replacement has to have text if we want to ensure both old and
        # new versions of a script are included. Use a single word (so it
        # can't be broken up) that is unlikely to appear in text.
        replacement.append(f'$[{replacement_id}]$')
        element.replace_with(replacement)

    return (soup, replacements)


def _add_undiffable_content(soup, replacements):
    """
    This is the opposite operation of `_remove_undiffable_content()`. It
    takes a soup and a replacement dict and replaces nodes in the soup that
    have the attribute `wm-diff-replacement"some ID"` with the original content
    from the replacements dict.
    """
    for element in soup.select('[wm-diff-replacement]'):
        replacement = replacements[element['wm-diff-replacement']]
        if replacement:
            element.replace_with(replacement)

    return soup


def _get_title(soup):
    return soup.title and soup.title.string or ''


def _diff_title(old, new):
    return ''.join(map(
        lambda change: ((change[0] == -1 and '<del>{}</del>')
                        or (change[0] == 1 and '<ins>{}</ins>')
                        or '{}').format(change[1]),
        compute_dmp_diff(_get_title(old), _get_title(new))))


def _diff_elements(old, new):
    """
    Diff the contents of two Beatiful Soup elements. Note that this returns
    the "new" element with its content replaced by the diff.
    """
    if not old or not new:
        return ''
    result_element = copy.copy(new)
    result_element.clear()
    result_element.append(_htmldiff(str(old), str(new)))
    return result_element


def _htmldiff(old, new):
    """
    A slightly customized version of htmldiff that uses different tokens.
    """
    old_tokens = tokenize(old)
    new_tokens = tokenize(new)
    old_tokens = [_customize_token(token) for token in old_tokens]
    new_tokens = [_customize_token(token) for token in new_tokens]
    result = htmldiff_tokens(old_tokens, new_tokens)
    result = ''.join(result).strip()
    return fixup_ins_del_tags(result)


class MinimalHrefToken(href_token):
    """
    A diffable token representing the URL of an <a> element. This allows the
    URL of a link to be diffed. However, we don't actually want to *render*
    the URL in the output (it's quite noisy in practice).

    Future revisions may change this for more complex, useful output.
    """
    def html(self):
        return ''


def _customize_token(token):
    """
    Replace existing diffing tokens with customized ones for better output.
    """
    if isinstance(token, href_token):
        return MinimalHrefToken(
            str(token),
            pre_tags=token.pre_tags,
            post_tags=token.post_tags,
            trailing_whitespace=token.trailing_whitespace)
    else:
        return token


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
    css = """
diffins {text-decoration : none; background-color: #d4fcbc;}
diffdel {text-decoration : none; background-color: #fbb6c2;}
diffins * {text-decoration : none; background-color: #d4fcbc;}
diffdel * {text-decoration : none; background-color: #fbb6c2;}
    """
    d = htmltreediff.diff(a_text, b_text,
                          ins_tag='diffins',del_tag='diffdel',
                          pretty=True)
    return insert_style(d, css)


def html_differ(a_text, b_text):
    css = """
.htmldiffer_insert {text-decoration : none; background-color: #d4fcbc;}
.htmldiffer_delete {text-decoration : none; background-color: #fbb6c2;}
.htmldiffer_insert * {text-decoration : none; background-color: #d4fcbc;}
.htmldiffer_delete * {text-decoration : none; background-color: #fbb6c2;}
    """
    d = HTMLDiffer(a_text, b_text).combined_diff
    return insert_style(d, css)
