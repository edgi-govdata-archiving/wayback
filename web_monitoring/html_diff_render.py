"""
This HTML-diffing implementation is based on LXML’s `html.diff` module. It is
meant to create HTML documents that can be viewed in a browser to highlight
and visualize portions of the page that changed.

We’ve tweaked the implementation of LXML’s diff algorithm significantly, to the
point where this is nearly a fork. It may properly become one in the future.

For now, you can mentally divide this module into two sections:

1. A higher-level routine that wraps the underlying diff implementation and
   formats responses. (The entry point for this is html_diff_render.)
2. A heavily modified version of LXML’s `html.diff`. It still leverages and
   depends on some parts of the LXML module, but that could change. (The entry
   point for this is _htmldiff)
"""

from bs4 import BeautifulSoup, Comment
from collections import namedtuple
import copy
import html
import logging
from lxml.html.diff import (tokenize, href_token, tag_token, expand_tokens,
                            InsensitiveSequenceMatcher)
from lxml.html.diff import token as DiffToken
from .differs import compute_dmp_diff

logger = logging.getLogger(__name__)

# This *really* means don't cross the boundaries of these elements with
# insertion/deletion elements. Instead, break the insertions/deletions in two.
# TODO: custom elements are iffy here. Maybe include them? (any tag with a `-`
# in the name)
block_level_tags = (
    'address',
    'article',
    'aside',
    'blockquote',
    'caption',
    'center',  # historic
    'dd',
    'details',
    'dialog',
    'dir',  # historic
    'div',
    'dl',
    'dt',
    'fieldset',
    'figcaption',
    'figure',
    'frameset',  # historic
    'footer',
    'form',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'header',
    'hgroup',
    'hr',
    'isindex',  # historic
    'li',
    'main',
    'menu',
    'nav',
    'noframes',  # historic
    'ol',
    'p',
    'pre',
    'section',
    'summary',
    'table',
    'ul',

    # Not "block" exactly, but don't cross its boundary
    'colgroup',
    'tbody',
    'thead',
    'tfoot',
    'tr',
    'td',
    'th',
    'noscript',
    'canvas',

    # These are "transparent", which means they *can* be a block
    'a',
    'del',
    'ins',
    'slot',
)

empty_tags = (
    'area',
    'base',
    'basefont',
    'br',
    'col',
    'embed',
    'img',
    'iframe',  # TODO: make sure we treat these right -- they need closing tags
    'input',
    'link',
    'meta',
    'param',
    'source',
    'track',
    'wbr'
)

# Should be treated as a single unit for diffing purposes -- their content is not HTML
# TODO: fork the tokenization part of lxml.html.diff and use this list!
undiffable_content_tags = (
    'datalist',  # Still HTML content, but we can’t really diff inside
    'math',
    'option',
    'rp',
    'script',
    'select',  # Still HTML content, but we can’t really diff inside
    'style',
    'svg',
    'template',
    'textarea'
)

# Elements that are not allowed to have our change elements as direct children
# TODO: add a cleanup step that respects this situation
no_change_children_tags = (
    'colgroup',
    'dl',
    'hgroup',
    'menu',
    'ol',
    'optgroup',
    'picture',
    'select',
    'table',
    'tbody',
    'thead',
    'tfoot',
    'tr',
    'ul',
)

# TODO: do we need special treatment for `<picture>`? Kind of like `<img>`

# Active elements are those that don't render, but affect other elements on the
# page. When viewing a combined diff, these elements need to be "deactivated"
# so their old and new versions don't compete.
ACTIVE_ELEMENTS = ('script', 'style')

# This diff is fundamentally a word-by-word diff, which attempts to re-assemble
# the tags that were present before or after a word after diffing the text.
# To help ensure a sense of structure is still involved in the diff, we look
# words preceded by these tags and add several special, matchable tokens in
# front of the word so that the actual diff algorithm sees some "sameness."
#
# One would *think* including `<h#>` tags here would make sense, but it turns
# out we've seen a variety of real-world situations where tags flip from inline
# markup to headings or headings nested by themselves (!) in other structural
# markup, making them cause frequent problems if included here.
SEPARATABLE_TAGS = ['blockquote', 'section', 'article', 'header', 'footer',
                    'pre', 'ul', 'ol', 'li', 'table', 'p']
# SEPARATABLE_TAGS = block_level_tags


def html_diff_render(a_text, b_text, include='combined'):
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
    # <script> or <style> that embed foreign content that shouldn't be parsed
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

    diff_bodies = diff_elements_multiply(soup_old.body, soup_new.body, include)
    results = {}
    for diff_type, diff_body in diff_bodies.items():
        soup = None
        replacements = None
        if diff_type == 'deletions':
            soup = copy.copy(soup_old)
            replacements = copy.copy(replacements_old)
        elif diff_type == 'insertions':
            soup = copy.copy(soup_new)
            replacements = copy.copy(replacements_new)
        else:
            replacements = copy.copy(replacements_new)
            replacements.update(replacements_old)
            soup = copy.copy(soup_new)
            title_meta = soup.new_tag(
                'meta',
                content=_diff_title(soup_old, soup_new))
            title_meta.attrs['name'] = 'wm-diff-title'
            soup.head.append(title_meta)

            old_head = soup.new_tag('template', id='wm-diff-old-head')
            if soup_old.head:
                for node in soup_old.head.contents.copy():
                    old_head.append(copy.copy(node))
            soup.head.append(old_head)

        change_styles = soup.new_tag(
            "style",
            type="text/css",
            id='wm-diff-style')
        change_styles.string = """
            ins, ins > * {text-decoration: none; background-color: #d4fcbc;}
            del, del > * {text-decoration: none; background-color: #fbb6c2;}"""
        soup.head.append(change_styles)

        soup.body.replace_with(diff_body)
        # The method we use above to append HTML strings (the diffs) to the soup
        # results in a non-navigable soup. So we serialize and re-parse :(
        # (Note we use no formatter for this because proper encoding escapes
        # the tags our differ generated.)
        soup = BeautifulSoup(soup.prettify(formatter=None), 'lxml')
        soup = _add_undiffable_content(
            soup,
            replacements,
            diff_type == 'combined')
        results[diff_type] = soup.prettify(formatter='minimal')

    return results


def _remove_undiffable_content(soup, prefix=''):
    """
    Find nodes that cannot be diffed (e.g. <script>, <style>) and replace them
    with an empty node that has the attribute `wm-diff-replacement="some ID"`

    Returns a tuple of the cleaned-up soup and a dict of replacements.
    """
    replacements = {}

    # NOTE: we may want to consider treating <object> and <canvas> similarly.
    # (They are "transparent" -- containing DOM, but only as a fallback.)
    for index, element in enumerate(soup.find_all(['script', 'style', 'svg', 'math'])):
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


def _add_undiffable_content(soup, replacements, deactivate_old=True):
    """
    This is the opposite operation of `_remove_undiffable_content()`. It
    takes a soup and a replacement dict and replaces nodes in the soup that
    have the attribute `wm-diff-replacement"some ID"` with the original content
    from the replacements dict.

    If `deactivate_old` is true, "old" replacements from the "before" version
    of the page will be wrapped in `<template>` tags so that they are
    non-functional.
    """
    for element in soup.select('[wm-diff-replacement]'):
        replacement_id = element['wm-diff-replacement']
        replacement = replacements[replacement_id]
        if replacement:
            replacement = copy.copy(replacement)
            css_class = replacement.get('class', [])
            if replacement_id.startswith('old-'):
                replacement['class'] = css_class + ['wm-diff-deleted-active']
                if replacement.name in ACTIVE_ELEMENTS and deactivate_old:
                    wrapper = soup.new_tag('template')
                    wrapper['class'] = 'wm-diff-deleted-inert'
                    wrapper.append(replacement)
                    replacement = wrapper
            else:
                replacement['class'] = css_class + ['wm-diff-inserted-active']
            element.replace_with(replacement)

    return soup


def get_title(soup):
    "Get the title of a Beautiful Soup document."
    return soup.title and soup.title.string or ''


def _html_for_dmp_operation(operation):
    "Convert a diff-match-patch operation to an HTML string."
    html_value = html.escape(operation[1])
    if operation[0] == -1:
        return f'<del>{html_value}</del>'
    elif operation[0] == 1:
        return f'<ins>{html_value}</ins>'
    else:
        return html_value


def _diff_title(old, new):
    """
    Create an HTML diff (i.e. a string with `<ins>` and `<del>` tags) of the
    title of two Beautiful Soup documents.
    """
    diff = compute_dmp_diff(get_title(old), get_title(new))
    return ''.join(map(_html_for_dmp_operation, diff))


def diff_elements(old, new, include='combined'):
    """
    Diff the contents of two Beatiful Soup elements. Note that this returns
    the "new" element with its content replaced by the diff.
    """
    if not old or not new:
        return ''
    result_element = copy.copy(new)
    result_element.clear()
    result_element.append(_htmldiff(str(old), str(new), include)[include])
    return result_element


def diff_elements_multiply(old, new, include='all'):
    results = {}
    if not old or not new:
        return results

    def fill_element(element, diff):
        result_element = copy.copy(element)
        result_element.clear()
        result_element.append(diff)
        return result_element

    diffs = {}
    for diff_type, diff in _htmldiff(str(old), str(new), include).items():
        element = diff_type == 'deletions' and old or new
        diffs[diff_type] = fill_element(element, diff)

    return diffs


def _htmldiff(old, new, include='all'):
    """
    A slightly customized version of htmldiff that uses different tokens.
    """
    old_tokens = tokenize(old)
    new_tokens = tokenize(new)
    # old_tokens = [_customize_token(token) for token in old_tokens]
    # new_tokens = [_customize_token(token) for token in new_tokens]
    old_tokens = _customize_tokens(old_tokens)
    new_tokens = _customize_tokens(new_tokens)
    # result = htmldiff_tokens(old_tokens, new_tokens)
    # result = diff_tokens(old_tokens, new_tokens) #, include='delete')
    logger.debug('CUSTOMIZED!')

    # HACK: The whole "spacer" token thing above in this code triggers the
    # `autojunk` mechanism in SequenceMatcher, so we need to explicitly turn
    # that off. That's probably not great, but I don't have a better approach.
    matcher = InsensitiveSequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    # matcher = SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    opcodes = matcher.get_opcodes()

    results = {}

    def render_diff(diff_type):
        diff = assemble_diff(old_tokens, new_tokens, opcodes, diff_type)
        # return fixup_ins_del_tags(''.join(diff).strip())
        result = ''.join(diff).strip().replace('</li> ', '</li>')
        return result

    if include == 'all' or include == 'combined':
        results['combined'] = render_diff('combined')
    if include == 'all' or include == 'insertions':
        results['insertions'] = render_diff('insertions')
    if include == 'all' or include == 'deletions':
        results['deletions'] = render_diff('deletions')

    return results


class MinimalHrefToken(href_token):
    """
    A diffable token representing the URL of an <a> element. This allows the
    URL of a link to be diffed. However, we don't actually want to *render*
    the URL in the output (it's quite noisy in practice).

    Future revisions may change this for more complex, useful output.
    """
    def html(self):
        # FIXME: we really do need some kind of sentinel here, even if we
        # only use it to track that there was a potential URL change. If the
        # URL diff does not coalesce with the link text, this becomes an empty
        # `<ins>/<del>` element and is probably not user-visible.
        # On the flip side, these can often get spuriously rendered because of
        # the same coalescing.
        #
        # Maybe: render a special tag, e.g. `<span class="wm-diff-url">`, then,
        # when cleaning up the diff, find instances of that tag, examine the
        # parent `<a>` element, and do something special if the link really
        # did change. Otherwise, delete it.
        #
        # Also: any such sentinel element MUST be one the lxml diffr thinks is
        # "empty" (i.e. self-closing). Otherwise, it may spuriously move a
        # subsequent change back through the document *into* the sentinel when
        # attempting to clean and "re-balance" the DOM tree. So, it must be one
        # of: [param, img, area, br, basefont, input, base, meta, link, col]
        return ''


# Explicitly designed to render repeatable crap so you can force-create
# unchanged areas in the diff, but not render that crap to the final result.
class SpacerToken(DiffToken):
    # def __new__(cls, text, pre_tags=None, post_tags=None, trailing_whitespace=""):
    #     obj = _unicode.__new__(cls, text)

    #     if pre_tags is not None:
    #         obj.pre_tags = pre_tags
    #     else:
    #         obj.pre_tags = []

    #     if post_tags is not None:
    #         obj.post_tags = post_tags
    #     else:
    #         obj.post_tags = []

    #     obj.trailing_whitespace = trailing_whitespace
    #     return obj

    def html(self):
        return ''


# I had some weird concern that I needed to make this token a single word with
# no spaces, but now that I know this differ more deeply, this is pointless.
class ImgTagToken(tag_token):
    def __new__(cls, tag, data, html_repr, pre_tags=None,
                post_tags=None, trailing_whitespace=""):
        obj = DiffToken.__new__(cls, "\n\nImg:%s\n\n" % data,
                            pre_tags=pre_tags,
                            post_tags=post_tags,
                            trailing_whitespace=trailing_whitespace)
        obj.tag = tag
        obj.data = data
        obj.html_repr = html_repr
        return obj


def _customize_tokens(tokens):
    SPACER_STRING = '\nSPACER'

    # Balance out pre- and post-tags so that a token of text is surrounded by
    # the opening and closing tags of the element it's in. For example:
    #
    #    <p><a>Hello!</a></p><div>…there.</div>
    #
    # Currently parses as:
    #    [('Hello!', pre=['<p>','<a>'], post=[]),
    #     ('…there.', pre=['</a>','</p>','<div>'], post=['</div>'])]
    #    (Note the '</div>' post tag is only present at the end of the doc)
    #
    # But this attempts make it more like:
    #
    #    [('Hello!', pre=['<p>','<a>'], post=['</a>','</p>']),
    #     ('…there.', pre=[<div>'], post=['</div>'])]
    #
    # TODO: when we get around to also forking the parse/tokenize part of this
    # diff, do this as part of the original tokenization instead.
    for token_index, token in enumerate(tokens):
        # logger.debug(f'Handling token {token_index}: {token}')
        if token_index == 0:
            continue
        previous = tokens[token_index - 1]
        previous_post_complete = False
        for post_index, tag in enumerate(previous.post_tags):
            if not tag.startswith('</'):
                # TODO: should we attempt to fill pure-structure tags here with
                # spacers? e.g. should we take the "<p><em></em></p>" here and
                # wrap a spacer token in it instead of moving to "next-text's"
                # pre_tags? "text</p><p><em></em></p><p>next-text"
                token.pre_tags = previous.post_tags[post_index:] + token.pre_tags
                previous.post_tags = previous.post_tags[:post_index]
                previous_post_complete = True
                break

        if not previous_post_complete:
            for pre_index, tag in enumerate(token.pre_tags):
                if not tag.startswith('</'):
                    if pre_index > 0:
                        previous.post_tags.extend(token.pre_tags[:pre_index])
                        token.pre_tags = token.pre_tags[pre_index:]
                    break
            else:
                previous.post_tags.extend(token.pre_tags)
                token.pre_tags = []


        # logger.debug(f'  Result...\n    pre: {token.pre_tags}\n    token: "{token}"\n    post: {token.post_tags}')

    result = []
    # for token in tokens:
    for token_index, token in enumerate(tokens):
        # if str(token).lower().startswith('impacts'):
        # if str(token).lower().startswith('although'):
        #     logger.debug(f'SPECIAL TAG!\n  pre: {token.pre_tags}\n  token: "{token}"\n  post: {token.post_tags}')

        # hahaha, this is crazy. But anyway, insert "spacers" that have
        # identical text the diff algorithm can latch onto as an island of
        # unchangedness. We do this anywhere a SEPARATABLE_TAG is opened.
        # Basically, this lets us create a sort of "wall" between changes,
        # ensuring a continuous insertion or deletion can't spread across
        # list items, major page sections, etc.
        # See farther down in this same method for a repeat of this with
        # `post_tags`
        try_splitting = len(token.pre_tags) > 0
        split_start = 0
        while try_splitting:
            for tag_index, tag in enumerate(token.pre_tags[split_start:]):
                split_here = False
                for name in SEPARATABLE_TAGS:
                    if tag.startswith(f'<{name}'):
                        split_here = True
                        break
                if split_here:
                    # new_token = SpacerToken(SPACER_STRING, pre_tags=token.pre_tags[0:tag_index + 1])
                    # token.pre_tags = token.pre_tags[tag_index + 1:]

                    new_token = SpacerToken(SPACER_STRING, pre_tags=token.pre_tags[0:tag_index + split_start])
                    token.pre_tags = token.pre_tags[tag_index + split_start:]

                    # tokens.insert(token_index + 1, token)
                    # token = new_token
                    result.append(new_token)
                    result.append(SpacerToken(SPACER_STRING))
                    result.append(SpacerToken(SPACER_STRING))
                    try_splitting = len(token.pre_tags) > 1
                    split_start = 1
                    break
                else:
                    try_splitting = False


        # This is a CRITICAL scenario, but should probably be generalized and
        # a bit better understood. The case is empty elements that are fully
        # nested inside something, so you have a structure like:
        #
        #   <div><span><a></a></span></div><div>Text!</div>
        #
        # All the tags preceeding `Text!` get set as pre_tags for `Text!` and,
        # later, when stuff gets rebalanced, `Text!` gets moved down inside the
        # <div> that completely precedes it.
        for index, tag in enumerate(token.pre_tags):
            if tag.startswith('<a') and len(token.pre_tags) > index + 1:
                next_tag = token.pre_tags[index + 1]
                if next_tag and next_tag.startswith('</a'):
                    result.append(SpacerToken('~EMPTY~', pre_tags=token.pre_tags[0:index], post_tags=token.pre_tags[index:]))
                    token.pre_tags = []

        # if _has_separation_tags(token.pre_tags):
        #     # result.append(SpacerToken(SPACER_STRING, token.pre_tags))
        #     # token.pre_tags = []
        #     result.append(SpacerToken(SPACER_STRING))
        #     result.append(SpacerToken(SPACER_STRING))

        customized = _customize_token(token)
        result.append(customized)

        if str(customized) == "Posts" and str(tokens[token_index - 1]) == 'Other' and str(tokens[token_index - 2]) == 'and': # and str(tokens[token_index - 3]) == 'posts':
            logger.debug(f'SPECIAL TAG!\n  pre: {token.pre_tags}\n  token: "{token}"\n  post: {token.post_tags}')
            next_token = tokens[token_index + 1]
            logger.debug(f'SPECIAL TAG!\n  pre: {next_token.pre_tags}\n  token: "{next_token}"\n  post: {next_token.post_tags}')
            for tag_index, tag in enumerate(customized.post_tags):
                if tag.startswith('</ul>'):
                    new_token = SpacerToken(SPACER_STRING)
                    result.append(new_token)
                    new_token = SpacerToken(SPACER_STRING, pre_tags=customized.post_tags[tag_index:])
                    result.append(new_token)
                    customized.post_tags = customized.post_tags[:tag_index]

        # if isinstance(customized, ImgTagToken):
        #     result.append(SpacerToken(SPACER_STRING))
        #     result.append(SpacerToken(SPACER_STRING))
        #     result.append(SpacerToken(SPACER_STRING))
        #     logger.debug(f'IMAGE TOKEN:')
        #     logger.debug(f'  pre: {customized.pre_tags}\n  token: "{customized}"\n  post: {customized.post_tags}')

        # if len(customized.post_tags) > 0:
        #     result.append(SpacerToken('', post_tags=customized.post_tags))
        #     customized.post_tags = []

        # if (_has_separation_tags(customized.post_tags)):
        #     result.append(SpacerToken(SPACER_STRING, pre_tags=customized.post_tags))
        #     # result.append(SpacerToken(SPACER_STRING, post_tags=customized.post_tags, trailing_whitespace=customized.trailing_whitespace))
        #     customized.post_tags = []
        #     # customized.trailing_whitespace = ''
        for tag_index, tag in enumerate(customized.post_tags):
            split_here = False
            for name in SEPARATABLE_TAGS:
                if tag.startswith(f'<{name}'):
                    split_here = True
                    break
            if split_here:
                # new_token = SpacerToken(SPACER_STRING, pre_tags=customized.post_tags[tag_index + 1:])
                # customized.post_tags = customized.post_tags[0:tag_index + 1]

                # new_token = SpacerToken(SPACER_STRING, pre_tags=customized.post_tags[tag_index:])
                # customized.post_tags = customized.post_tags[0:tag_index]

                new_token = SpacerToken(SPACER_STRING, post_tags=customized.post_tags[tag_index:])
                customized.post_tags = customized.post_tags[0:tag_index]

                # tokens.insert(token_index + 1, token)
                # token = new_token
                result.append(new_token)
                result.append(SpacerToken(SPACER_STRING))
                result.append(SpacerToken(SPACER_STRING))
                break

    return result


# One would *think* including `<h#>` tags here would make sense, but it turns
# out we've seen a variety of real-world situations where tags flip from inline
# markup to headings or headings nested by themselves (!) in other structural
# markup, making them cause frequent problems if included here.
SEPARATABLE_TAGS = ['blockquote', 'section', 'article', 'header',
                    'footer', 'pre', 'ul', 'ol', 'li', 'table', 'p']
HEADING_TAGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
def _has_separation_tags(tag_list):
    for index, tag in enumerate(tag_list):
        for name in SEPARATABLE_TAGS:
            if tag.startswith(f'<{name}') or tag.startswith(f'</{name}'):
                logger.debug(f'Separating on: {name}')
                return True
        if 'id=' in tag:
            return True
    return False

def _has_heading_tags(tag_list):
    for index, tag in enumerate(tag_list):
        for name in HEADING_TAGS:
            if tag.startswith(f'<{name}') or tag.startswith(f'</{name}'):
                return True


# Seemed so nice and clean! But should probably be merged into
# `_customize_tokens()` now. Or otherwise it needs to be able to produce more
# than one token to replace the given token in the stream.
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
    elif isinstance(token, tag_token) and token.tag == 'img':
        # logger.debug('TAG TOKEN: %s' % token)
        return ImgTagToken(
            'img',
            data=token.data,
            html_repr=token.html_repr,
            pre_tags=token.pre_tags,
            post_tags=token.post_tags,
            trailing_whitespace=token.trailing_whitespace)
        # return token
    else:
        return token


# TODO: merge and reconcile this with `merge_change_groups()`, which is 90%
# the same thing; it outputs the change elements as nested lists of tokens.
def merge_changes(change_chunks, doc, tag_type='ins'):
    """
    Merge tokens that were changed into a list of tokens (that represents the
    whole document) and wrap them with a tag.

    This will break the changed sections into multiple elements as needed to
    ensure that changes don't cross the boundaries of some elements, like
    `<header>` or `<p>`. For example, you'd get three `<ins>` elements here:

        <ins>Some</ins><p><ins>inserted</ins></p><ins>text</ins>

    Parameters
    ----------
    change_chunks : list of token
        The changes to merge.
    doc : list of token
        The "document" to merge `change_chunks` into.
    tag_type : str
        The type of HTML tag to wrap the changes with.
    """
    # NOTE: this serves a similar purpose to LXML's html.diff.merge_insert
    # function, though this is much more complicated. LXML's version takes a
    # simpler approach to placing tags, then later runs the whole thing through
    # an XML parser, manipulates the tree, and re-serializes. We don't do that
    # here because it turns out to exacerbate some errors in the placement of
    # insert and delete tags. Think of it like splinting a broken bone without
    # setting it first.
    #
    # Here, we actually attempt to keep track of the stack of elements and
    # proactively put tags in the right place and break them up so the
    # resulting token stream represents valid markup. Happily, that also means
    # we don't also have to do the expensive parse-then-serialize step later!
    depth = 0
    current_content = None
    for chunk in change_chunks:
        inline_tag = False
        inline_tag_name = None

        if chunk == '':
            continue

        # FIXME: explicitly handle elements that can't have our markers as
        # direct children.
        if chunk[0] == '<':
            name = chunk.split()[0].strip('<>/')
            # Also treat `a` tags as block in this context, because they *can*
            # contain block elements, like `h1`, etc.
            is_block = name in block_level_tags or name == 'a'

            if chunk[1] == '/':
                if depth > 0:
                    if is_block:
                        for nested_tag in current_content:
                            doc.append(f'</{nested_tag}>')
                        doc.append(f'</{tag_type}>')
                        current_content = None
                        depth -= 1
                        doc.append(chunk)
                    else:
                        if name in current_content:
                            index = current_content.index(name)
                            current_content = current_content[index + 1:]
                            doc.append(chunk)
                        else:
                            # only a malformed document should hit this case
                            # where tags aren't properly nested ¯\_(ツ)_/¯
                            for nested_tag in current_content:
                                doc.append(f'</{nested_tag}>')

                            doc.append(f'</{tag_type}>')
                            doc.append(chunk)
                            doc.append(f'<{tag_type}>')

                            # other side of the malformed document case from above
                            current_content.reverse()
                            for nested_tag in current_content:
                                doc.append(f'<{nested_tag}>')
                            current_content.reverse()
                else:
                    doc.append(chunk)
                # There is no case for a closing tag where aren't doen with the chunk
                continue
            else:
                entering_tag = name
                entering_inline_tag = not is_block

                if is_block:
                    if depth > 0:
                        for nested_tag in current_content:
                            doc.append(f'</{nested_tag}>')
                        doc.append(f'</{tag_type}>')
                        current_content = None
                        depth -= 1
                    doc.append(chunk)
                    continue
                else:
                    inline_tag = True
                    inline_tag_name = name

        if depth == 0:
            doc.append(f'<{tag_type}>')
            depth += 1
            current_content = []

        doc.append(chunk)
        if inline_tag and inline_tag_name not in empty_tags:
            # FIXME: track the original start tag for when we need to break
            # these elements around boundaries.
            current_content.insert(0, inline_tag_name)

    if depth > 0:
        for nested_tag in current_content:
            doc.append(f'</{nested_tag}>')

        doc.append(f'</{tag_type}>')

        current_content.reverse()
        for nested_tag in current_content:
            doc.append(f'<{nested_tag}>')


def assemble_diff(html1_tokens, html2_tokens, commands, include='combined'):
    """
    Assembles a renderable HTML string from a set of old and new tokens and a
    list of operations to perform agains them.
    """
    include_insert = include == 'combined' or include == 'insertions'
    include_delete = include == 'combined' or include == 'deletions'

    # Generating a combined diff view is a relatively complicated affair. We
    # keep track of all the consecutive insertions and deletions in buffers
    # until we find a portion of the document that is unchanged, at which point
    # we reconcile the DOM structures of the changes before inserting the
    # unchanged parts.
    result = []
    insert_buffer = []
    delete_buffer = []

    for command, i1, i2, j1, j2 in commands:
        if command == 'equal':
            # When encountering an unchanged series of tokens, we first expand
            # them to include the HTML elements that are attached to the
            # tokenized text. Then we find the changed HTML tags before and
            # after the unchanged text and add them to the previous buffer of
            # changes and the next buffer of changes, respectively. This
            # ensures that the reconciliation routine that handles differences
            # in DOM structure is used on them, while portions that are exactly
            # the same are simply inserted as-is.
            #
            # TODO: this splitting approach could probably be handled better if
            # it was part of or better integrated with expanding the tokens, so
            # we could just look at the first token's `pre_tags` and the last
            # token's `post_tags` instead of having to reverse engineer them.
            equal_buffer_delete = []
            equal_buffer_insert = []
            equal_buffer_delete_next = []
            equal_buffer_insert_next = []
            if include_insert and include_delete:
                merge_change_groups(
                    expand_tokens(html1_tokens[i1:i2], equal=True),
                    equal_buffer_delete,
                    tag_type=None)
                merge_change_groups(
                    expand_tokens(html2_tokens[j1:j2], equal=True),
                    equal_buffer_insert,
                    tag_type=None)

                first_delete_group = -1
                first_insert_group = -1
                for token_index, token in enumerate(equal_buffer_delete):
                    if isinstance(token, list):
                        first_delete_group = token_index
                        break
                for token_index, token in enumerate(equal_buffer_insert):
                    if isinstance(token, list):
                        first_insert_group = token_index
                        break
                # In theory we should always find both, but sanity check anyway
                if first_delete_group > -1 and first_insert_group > -1:
                    max_index = min(first_delete_group, first_insert_group)
                    unequal_reverse_index = max_index
                    for reverse_index in range(max_index):
                        delete_token = equal_buffer_delete[first_delete_group - 1 - reverse_index]
                        insert_token = equal_buffer_insert[first_insert_group - 1 - reverse_index]
                        if delete_token != insert_token:
                            unequal_reverse_index = reverse_index
                            break
                    delete_buffer.extend(equal_buffer_delete[:first_delete_group - unequal_reverse_index])
                    equal_buffer_delete = equal_buffer_delete[first_delete_group - unequal_reverse_index:]
                    insert_buffer.extend(equal_buffer_insert[:first_insert_group - unequal_reverse_index])
                    equal_buffer_insert = equal_buffer_insert[first_insert_group - unequal_reverse_index:]

                last_delete_group = -1
                last_insert_group = -1
                # FIXME: totally inefficient; should go backward
                for token_index, token in enumerate(equal_buffer_delete):
                    if isinstance(token, list):
                        last_delete_group = token_index
                for token_index, token in enumerate(equal_buffer_insert):
                    if isinstance(token, list):
                        last_insert_group = token_index

                # In theory we should always find both, but sanity check anyway
                if last_delete_group > -1 and last_insert_group > -1:
                    max_range = min(len(equal_buffer_delete) - last_delete_group, len(equal_buffer_insert) - last_insert_group)
                    unequal_index = max(1, max_range)
                    for index in range(1, max_range):
                        delete_token = equal_buffer_delete[last_delete_group + index]
                        insert_token = equal_buffer_insert[last_insert_group + index]
                        if delete_token != insert_token:
                            unequal_index = index
                            break
                    equal_buffer_delete_next = equal_buffer_delete[last_delete_group + unequal_index:]
                    equal_buffer_delete = equal_buffer_delete[:last_delete_group + unequal_index]
                    equal_buffer_insert_next = equal_buffer_insert[last_insert_group + unequal_index:]
                    equal_buffer_insert = equal_buffer_insert[:last_insert_group + unequal_index]

            if insert_buffer or delete_buffer:
                reconcile_change_groups(insert_buffer, delete_buffer, result)

            if include_insert and include_delete:
                result.extend(flatten_groups(equal_buffer_insert))
                delete_buffer.extend(equal_buffer_delete_next)
                insert_buffer.extend(equal_buffer_insert_next)
            elif include_insert:
                result.extend(expand_tokens(html2_tokens[j1:j2], equal=True))
            else:
                result.extend(expand_tokens(html1_tokens[i1:i2], equal=True))
            continue
        if (command == 'insert' or command == 'replace') and include_insert:
            ins_tokens = expand_tokens(html2_tokens[j1:j2])
            if include_delete:
                merge_change_groups(ins_tokens, insert_buffer, 'ins')
            else:
                merge_changes(ins_tokens, result, 'ins')
        if (command == 'delete' or command == 'replace') and include_delete:
            del_tokens = expand_tokens(html1_tokens[i1:i2])
            if include_insert:
                merge_change_groups(del_tokens, delete_buffer, 'del')
            else:
                merge_changes(del_tokens, result, 'del')

    reconcile_change_groups(insert_buffer, delete_buffer, result)
    return result


# TODO: merge and reconcile this with `merge_changes()`, which is 90% the same
# thing; it just outputs a flat instead of nested list.
def merge_change_groups(change_chunks, doc, tag_type=None):
    """
    Group tokens from a flat list of tokens into continuous mark-up-able
    groups. This mainly means being sensitive to HTML elements that we don't
    want tags representing changes to intersect with.

    For example, a change element shouldn't cross the boundaries of a `<p>`
    element. Instead, it should end before the `<p>`, restart again inside the
    `<p>`, and end and restart again before and after the `</p>` closing tag:

        <ins>Some</ins><p><ins>inserted</ins></p><ins>text</ins>

    While the input to this method is a flat list of tokens, the output is a
    mixed list of tokens (e.g. the `<p>`) and lists of tokens, which represent
    runs of tokens that can be fully wrapped in an element to represent changes
    (like `<ins>`). Note also that the output is not returned, but appended to
    the second argument (a document, or list of tokens, to output to). So the
    corresponding data structure to the above would be:

        Input:  ['Some','<p>','inserted','</p>','text']
        Output: [['<ins>','Some','</ins>'],
                 '<p>',
                 ['<ins>','inserted','</ins>'],
                 '</p>',
                 ['<ins>','text','</ins>']]

    The last argument, `tag_type` is the name of the tag to wrap the changes
    in, e.g. `ins`. If set to `None`, changes will still be grouped, but groups
    will not include wrapping tags.

    Parameters
    ----------
    change_chunks : list of token
        The changes to merge.
    doc : list of token
        The "document" to merge `change_chunks` into.
    tag_type : str
        The type of HTML tag to wrap the changes with.
    """
    depth = 0
    current_content = None
    group = doc
    for chunk in change_chunks:
        inline_tag = False
        inline_tag_name = None

        if chunk == '' or chunk == ' ':
            continue

        # FIXME: explicitly handle elements that can't have our markers as
        # direct children.
        if chunk[0] == '<':
            name = chunk.split()[0].strip('<>/')
            # Also treat `a` tags as block in this context, because they *can*
            # contain block elements, like `h1`, etc.
            is_block = name in block_level_tags or name == 'a'

            if chunk[1] == '/':
                if depth > 0:
                    if is_block:
                        for nested_tag in current_content:
                            group.append(f'</{nested_tag}>')
                        if tag_type:
                            group.append(f'</{tag_type}>')
                        current_content = None
                        depth -= 1
                        group = doc
                        group.append(chunk)
                    else:
                        if name in current_content:
                            index = current_content.index(name)
                            current_content = current_content[index + 1:]
                            group.append(chunk)
                        else:
                            # only a malformed document should hit this case
                            # where tags aren't properly nested ¯\_(ツ)_/¯
                            for nested_tag in current_content:
                                group.append(f'</{nested_tag}>')

                            if tag_type:
                                group.append(f'</{tag_type}>')
                            # <start> not sure if we should break the group
                            # group = doc
                            # <end> not sure if we should break the group
                            group.append(chunk)
                            # <start> not sure if we should break the group
                            # group = []
                            # doc.append(group)
                            # <end> not sure if we should break the group
                            if tag_type:
                                group.append(f'<{tag_type}>')

                            # other side of the malformed document case from above
                            current_content.reverse()
                            for nested_tag in current_content:
                                group.append(f'<{nested_tag}>')
                            current_content.reverse()
                else:
                    group.append(chunk)
                # There is no case for a closing tag where aren't doen with the chunk
                continue
            else:
                entering_tag = name
                entering_inline_tag = not is_block

                if is_block:
                    if depth > 0:
                        for nested_tag in current_content:
                            group.append(f'</{nested_tag}>')
                        if tag_type:
                            group.append(f'</{tag_type}>')
                        current_content = None
                        depth -= 1
                        group = doc
                    group.append(chunk)
                    continue
                else:
                    inline_tag = True
                    inline_tag_name = name

        if depth == 0:
            group = []
            doc.append(group)
            if tag_type:
                group.append(f'<{tag_type}>')
            depth += 1
            current_content = []

        group.append(chunk)
        if inline_tag and inline_tag_name not in empty_tags:
            # FIXME: track the original start tag for when we need to break
            # these elements around boundaries.
            current_content.insert(0, inline_tag_name)

    if depth > 0:
        for nested_tag in current_content:
            group.append(f'</{nested_tag}>')

        if tag_type:
            group.append(f'</{tag_type}>')
        group = doc

        current_content.reverse()
        for nested_tag in current_content:
            group.append(f'<{nested_tag}>')


TagInfo = namedtuple('TagInfo', ('name', 'open', 'source'))


# TODO: rewrite this in a way that doesn't mutate the input?
def reconcile_change_groups(insert_groups, delete_groups, document):
    """
    Attempt to reconcile a list of grouped tokens (see merge_change_groups())
    that were deleted with another list of those that were inserted in roughly
    the same place, resulting in a single, merged list of tokens that displays
    the two adjacent to each other in a correctly structured DOM.

    The merged list of tokens is appended to `document`, then each list of
    tokens is cleared.

    The basic idea here is that, where the two lists of tokens diverge, we
    create speculative branches. When the tokens added to a branch result in a
    complete tree, we add it to the resulting document. Incomplete insertion
    branches are added as-is at the end (because the overall combined document
    follows the structure of the new version of the HTML, not the old), while
    incomplete deletion branches are either synthetically completed by closing
    all their open tags (if they contain meaningful changes) or are simply
    thrown out (if they do not contain meaningful changes).
    """
    logger.debug('------------------ RECONCILING ----------------------')
    logger.debug(f'  INSERT:\n  {insert_groups}\n')
    logger.debug(f'  DELETE:\n  {delete_groups}\n')
    start_index = len(document)
    insert_index = 0
    delete_index = 0
    insert_count = len(insert_groups)
    delete_count = len(delete_groups)

    insert_tag_stack = []
    delete_tag_stack = []
    delete_tag_unstack = []
    insert_buffer = []
    delete_buffer = []
    buffer = document

    def tag_info(token):
        if not token.startswith('<'):
            return None
        name = token.split()[0].strip('<>/')
        return TagInfo(name, not token.startswith('</'), token)

    while True:
        insertion = insert_index < insert_count and insert_groups[insert_index] or None
        deletion = delete_index < delete_count and delete_groups[delete_index] or None
        if not insertion and not deletion:
            break

        # Strip here because tags can have whitespace attached to the end :\
        equal_items = insertion == deletion or (
            isinstance(insertion, str) and
            isinstance(deletion, str) and
            insertion.strip() == deletion.strip())

        if equal_items and buffer is document:
            document.append(insertion)
            insert_index += 1
            delete_index += 1
        elif isinstance(deletion, list):
            buffer.extend(deletion)
            delete_index += 1
        elif isinstance(insertion, list):
            buffer.extend(insertion)
            insert_index += 1
        elif deletion:
            tag = tag_info(deletion)
            if tag:
                if tag.open:
                    if delete_tag_unstack:
                        delete_buffer.append(deletion)
                        delete_index += 1
                        active_tag = delete_tag_unstack.pop()
                        if tag.name != active_tag.name:
                            delete_tag_unstack.append(active_tag)
                            delete_tag_unstack.append(tag)
                        if not delete_tag_unstack:
                            logger.debug(f'INSERTING DELETE UNSTACK BUFFER: {delete_buffer}')
                            document.extend(delete_buffer)
                            delete_buffer.clear()
                            buffer = document
                    else:
                        buffer = delete_buffer
                        delete_tag_stack.append(tag)
                        delete_buffer.append(deletion)
                        delete_index += 1
                else:
                    if delete_tag_stack:
                        active_tag = delete_tag_stack.pop()
                        while delete_tag_stack and active_tag.name != tag.name:
                            active_tag = delete_tag_stack.pop()
                        if active_tag.name != tag.name:
                            logger.warning(f'Close tag with no corresponding open tag found in deletions ({tag})')
                            break
                        delete_buffer.append(deletion)
                        delete_index += 1
                        if not delete_tag_stack:
                            logger.debug(f'INSERTING DELETE BUFFER: {delete_buffer}')
                            document.extend(delete_buffer)
                            delete_buffer.clear()
                            buffer = document
                    else:
                        # Speculatively go the opposite direction
                        buffer = delete_buffer
                        if delete_tag_unstack:
                            active_tag = delete_tag_unstack.pop()
                            if not active_tag.open:
                                delete_tag_unstack.append(active_tag)
                                delete_tag_unstack.append(tag)
                                delete_buffer.append(deletion)
                                delete_index += 1
                            elif active_tag.open and active_tag.name == tag.name:
                                delete_buffer.append(deletion)
                                delete_index += 1
                            else:
                                logger.warning('Close tag with no corresponding open tag found in unstacking deletions')
                                break
                        else:
                            delete_tag_unstack.append(tag)
                            delete_buffer.append(deletion)
                            delete_index += 1
                            # pass
            else:
                # NOTE: not sure we can ever reach this case (unwrapped change
                # that is not an element).
                buffer.append(deletion)
                delete_index += 1

        elif insertion:
            # if we have a hanging delete buffer (with content, not just HTML
            # DOM structure), clean it up and insert it before moving on.
            # FIXME: this should not look explicitly for `<del>`
            if '<del>' in delete_buffer:
                for tag in delete_tag_stack:
                    delete_buffer.append(f'</{tag[0]}>')
                document.extend(delete_buffer)
                delete_tag_stack.clear()
                delete_buffer.clear()

            tag = tag_info(insertion)
            if tag:
                if tag.open:
                    buffer = insert_buffer
                    insert_tag_stack.append(tag)
                    insert_buffer.append(insertion)
                    insert_index += 1
                else:
                    if insert_tag_stack:
                        active_tag = insert_tag_stack.pop()
                        while insert_tag_stack and active_tag.name != tag.name:
                            active_tag = insert_tag_stack.pop()
                        if active_tag.name != tag.name:
                            logger.warning('Close tag with no corresponding open tag found in insertions')
                            break
                        insert_buffer.append(insertion)
                        insert_index += 1
                        if not insert_tag_stack:
                            document.extend(insert_buffer)
                            insert_buffer.clear()
                            buffer = document
                    else:
                        # Insertions control the overall structure of the
                        # document. Don't move up a level until we are out of
                        # deletions at this level.
                        if not deletion:
                            document.append(insertion)
                            insert_index += 1

            else:
                # NOTE: not sure we can ever reach this case (unwrapped change
                # that is not an element).
                buffer.append(insertion)
                insert_index += 1

    # Add any hanging buffer of deletes that never got completed, but only if
    # it has salient changes in it.
    # FIXME: this should not look explicitly for `<del>`
    if '<del>' in delete_buffer:
        for tag in delete_tag_stack:
            delete_buffer.append(f'</{tag[0]}>')
        document.extend(delete_buffer)

    document.extend(insert_buffer)

    insert_groups.clear()
    delete_groups.clear()

    result = document[start_index:]
    logger.debug(f'  RESULT:\n  {result}\n')

    return document


def flatten_groups(groups, include_non_groups=True):
    flat = []
    for item in groups:
        if isinstance(item, list):
            flat.extend(item)
        elif include_non_groups:
            flat.append(item)

    return flat
