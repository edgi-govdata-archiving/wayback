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
import copy
import html
from lxml.html.diff import (tokenize, htmldiff_tokens, fixup_ins_del_tags,
                            href_token, tag_token, InsensitiveSequenceMatcher,
                            expand_tokens, merge_delete,
                            split_unbalanced, empty_tags)
from lxml.html.diff import token as DiffToken
from .differs import compute_dmp_diff

# This *really* means don't cross the boundaries of these elements with insertion/deletion elements. Instead, break the insertions and deletions in two.
# TODO: custom elements are iffy here. Maybe include them? (any tag with a `-` in the name)
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
    'iframe',  # TODO: make sure we treat these right -- they still need a closing tag
    'input',
    'link',
    'meta',
    'param',
    'source',
    'track',
    'wbr'
)

# Should be treated as a single unit for diffing purposes -- their content is not HTML
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
        # (Note we use no formatter for this because proper encoding escape the
        # tags our differ generated.)
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

    # HACK: The whole "spacer" token thing above in this code triggers the
    # `autojunk` mechanism in SequenceMatcher, so we need to explicitly turn
    # that off. That's probably not great, but I don't have a better approach.
    matcher = InsensitiveSequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    opcodes = matcher.get_opcodes()

    results = {}

    def render_diff(diff_type):
        diff = assemble_diff(old_tokens, new_tokens, opcodes, diff_type)
        return fixup_ins_del_tags(''.join(diff).strip())

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
    result = []
    # for token in tokens:
    for token_index, token in enumerate(tokens):
        # if str(token).lower().startswith('impacts'):
        if str(token).lower().startswith('although'):
            print(f'SPECIAL TAG!\n  pre: {token.pre_tags}\n  token: "{token}"\n  post: {token.post_tags}')

        # hahaha, this is crazy. But anyway, insert "spacers" that have
        # identical text the diff algorithm can latch onto as an island of
        # unchangedness. We do this anywhere a SEPARATABLE_TAG is opened.
        # Basically, this lets us create a sort of "wall" between changes,
        # ensuring a continuous insertion or deletion can't spread across
        # list items, major page sections, etc.
        # See farther down in this same method for a repeat of this with
        # `post_tags`
        try_splitting = len(token.pre_tags) > 0
        while try_splitting:
            for tag_index, tag in enumerate(token.pre_tags):
                split_here = False
                for name in SEPARATABLE_TAGS:
                    if tag.startswith(f'<{name}'):
                        split_here = True
                        break
                if split_here:
                    new_token = SpacerToken(SPACER_STRING, pre_tags=token.pre_tags[0:tag_index + 1])
                    token.pre_tags = token.pre_tags[tag_index + 1:]
                    # tokens.insert(token_index + 1, token)
                    # token = new_token
                    result.append(new_token)
                    result.append(SpacerToken(SPACER_STRING))
                    result.append(SpacerToken(SPACER_STRING))
                    try_splitting = len(token.pre_tags) > 0
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
        # if isinstance(customized, ImgTagToken):
        #     result.append(SpacerToken(SPACER_STRING))
        #     result.append(SpacerToken(SPACER_STRING))
        #     result.append(SpacerToken(SPACER_STRING))
        #     print(f'IMAGE TOKEN:')
        #     print(f'  pre: {customized.pre_tags}\n  token: "{customized}"\n  post: {customized.post_tags}')

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
                new_token = SpacerToken(SPACER_STRING, pre_tags=customized.post_tags[tag_index + 1:])
                customized.post_tags = customized.post_tags[0:tag_index + 1]
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
                print(f'Separating on: {name}')
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
        # print('TAG TOKEN: %s' % token)
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




def assemble_diff(html1_tokens, html2_tokens, commands, include='combined'):
    """
    Assembles a renderable HTML string from a set of old and new tokens and a
    list of operations to perform agains them.
    """
    include_insert = include == 'combined' or include == 'insertions'
    include_delete = include == 'combined' or include == 'deletions'

    # There are several passes as we do the differences.  The tokens
    # isolate the portion of the content we care to diff; difflib does
    # all the actual hard work at that point.
    #
    # Then we must create a valid document from pieces of both the old
    # document and the new document.  We generally prefer to take
    # markup from the new document, and only do a best effort attempt
    # to keep markup from the old document; anything that we can't
    # resolve we throw away.  Also we try to put the deletes as close
    # to the location where we think they would have been -- because
    # we are only keeping the markup from the new document, it can be
    # fuzzy where in the new document the old text would have gone.
    # Again we just do a best effort attempt.
    result = []
    # HACK: Check out this insane "buffer" mechanism! This seems to help get
    # deletions properly located in cases where the trailing tag content on set
    # of tokens differs between the old and new document.
    buffer = []
    post_equality = []
    for command, i1, i2, j1, j2 in commands:
        # for index, command_data in enumerate(commands):
        #     command, i1, i2, j1, j2 = command_data

        if command == 'equal':
            if post_equality:
                result.extend(post_equality)
                post_equality = []
            if buffer:
                result.extend(buffer)
                buffer = []

            if include_insert:
                token = html2_tokens[j2 - 1]
                token2 = html1_tokens[i2 - 1]
                print(f'Ending equality with...')
                print(f'  pre: {token2.pre_tags}\n  token: "{token2}"\n  post: {token2.post_tags}')
                print(f'  --vs--\n  pre: {token.pre_tags}\n  token: "{token}"\n  post: {token.post_tags}')
                if html2_tokens[j2 - 1].post_tags and not html1_tokens[i2 - 1].post_tags:
                    buffer.extend(html2_tokens[j2 - 1].post_tags)
                    html2_tokens[j2 - 1].post_tags = []
                    print('Buffering!')
                # else:
                #     last_delete = html1_tokens[i2 - 1]
                #     last_insert = html2_tokens[j2 - 1]
                #     if (_has_heading_tags(last_insert.post_tags) or _has_separation_tags(last_insert.post_tags)) \
                #        and not (_has_heading_tags(last_delete.post_tags) or _has_separation_tags(last_delete.post_tags)):
                #         post_equality.extend(html2_tokens[j2 - 1].post_tags)
                #         html2_tokens[j2 - 1].post_tags = []
                #         print('POST_EQUALIZING')
                result.extend(expand_tokens(html2_tokens[j1:j2], equal=True))
            else:
                result.extend(expand_tokens(html1_tokens[i1:i2], equal=True))
            continue
        if (command == 'insert' or command == 'replace') and include_insert:
            if post_equality:
                result.extend(post_equality)
                post_equality = []
            if command == 'insert':
                print(f'INSERTING at {j1}:{j2} (old doc {i1}:{i2})')
            else:
                print(f'REPLACING at {j1}:{j2} (old doc {i1}:{i2})')

            print('Starting INSERTION with...')
            for insert_token in html1_tokens[i1:i2]:
                nice_token = insert_token.replace('\n', '\\n')
                print(f'    {insert_token.pre_tags} "{nice_token}" {insert_token.post_tags}')
            print(f'  --vs--')
            for insert_token in html2_tokens[j1:j2]:
                nice_token = insert_token.replace('\n', '\\n')
                print(f'    {insert_token.pre_tags} "{nice_token}" {insert_token.post_tags}')

            should_buffer = False
            # if command == 'replace':
            #     last_delete = html1_tokens[i2 - 1]
            #     last_insert = html2_tokens[j2 - 1]
            #     if (_has_heading_tags(last_insert.post_tags) or _has_separation_tags(last_insert.post_tags)) \
            #        and not (_has_heading_tags(last_delete.post_tags) or _has_separation_tags(last_delete.post_tags)):
            #         print('BUFFERING')
            #         should_buffer = True

            # token = html2_tokens[j1]
            # token2 = html1_tokens[i1]
            # print(f'Starting INSERTION with...')
            # print(f'  pre: {token.pre_tags}\n  token: "{token}"\n  post: {token.post_tags}')
            # print(f'  --vs--\n  pre: {token2.pre_tags}\n  token: "{token2}"\n  post: {token2.post_tags}')

            # token = html2_tokens[j2 - 1]
            # token2 = html1_tokens[i2 - 1]
            # print(f'Ending INSERTION with...')
            # print(f'  pre: {token.pre_tags}\n  token: "{token}"\n  post: {token.post_tags}')
            # print(f'  --vs--\n  pre: {token2.pre_tags}\n  token: "{token2}"\n  post: {token2.post_tags}')

            # if buffer:
            #     print(f'Insert Unbuffering: {buffer}')
            # result.extend(buffer)
            # buffer = []
            ins_tokens = expand_tokens(html2_tokens[j1:j2])
            if buffer or should_buffer:
                merge_changes(ins_tokens, buffer)
            else:
                merge_changes(ins_tokens, result)
        if (command == 'delete' or command == 'replace') and include_delete:
            # if command == 'replace' and html1_tokens[i1].pre_tags == html2_tokens[j1].pre_tags:
            #     html1_tokens[i1].pre_tags = []
            # if command == 'replace' and html1_tokens[i2 - 1].post_tags == html2_tokens[j2 - 1].post_tags:
            #     html1_tokens[i2 - 1].post_tags = []

            del_tokens = expand_tokens(html1_tokens[i1:i2])
            if include_insert:
                merge_speculative_deletions(del_tokens, result)
            else:
                merge_changes(del_tokens, result, 'del')

            if buffer:
                print(f'Delete Unbuffering: {buffer}')
            result.extend(buffer)
            buffer = []
            if post_equality:
                result.extend(post_equality)
                post_equality = []
    # If deletes were inserted directly as <del> then we'd have an
    # invalid document at this point.  Instead we put in special
    # markers, and when the complete diffed document has been created
    # we try to move the deletes around and resolve any problems.
    result.extend(buffer)

    if include_insert and include_delete:
        result = cleanup_delete(result)

    return result


def merge_changes(change_chunks, doc, tag_type='ins'):
    """
    Merge tokens that were changed into a list of tokens (that represents the
    whole document) and wrap them with a tag.

    This is largely the same as lxml.html.diff.merge_insert, but allows any
    tag to be used, since we need to be able to also merge deletions this way,
    not just insertions.

    Parameters
    ----------
    change_chunks : list of token
        The changes to merge.
    doc : list of token
        The "document" to merge `change_chunks` into.
    tag_type : str
        The type of HTML tag to wrap the changes with.
    """
    # # Though we don't throw away unbalanced_start or unbalanced_end
    # # (we assume there is accompanying markup later or earlier in the
    # # document), we only put <ins> around the balanced portion.
    change_chunks = list(change_chunks)
    unbalanced_start, balanced, unbalanced_end = split_unbalanced(change_chunks)
    print('------------- INSERTING CHANGE ---------------')
    print(f'  [START] {unbalanced_start}\n  <{tag_type}>\n  {balanced}\n  </{tag_type}>\n  {unbalanced_end}')

    # HOLY MOLY WHAT IS HAPPENING HERE???????? WELL...
    # The commented out implementation below is basically the same as the
    # implementation in LXML (with the tweak that you can specify a tag name).
    # However, it turns out to have had a few big problems:
    #   1. Because it doesn't include "unbalanced" parts of the change, the
    #      marked-up content might not actually match the whole change!
    #
    #   2. split_unbalanced can *really* screw up the DOM! Take this example:
    #
    #      >>> diff.split_unbalanced(['<div1>','hello','</div1>','</div2>','there','</div1>','more'])
    #      ([], ['<div1>', 'hello', '</div1>', 'there', 'more'], ['</div2>', '</div1>'])
    #
    #      See how content got totally moved around? This even that contrived;
    #      we could have totally valid markup like the above because we are
    #      working with random fragments of source (not the tree). In the
    #      example above, the change we're working with could have come right
    #      after the markup `<div1><div2>Some prefixed text` and it’d be fine.
    #
    #   3. This method winds up with `ins/del` elements surrounding block-level
    #      elements when they should be inside them. The fixup_ins_del_tags
    #      function that gets run later tries to fix this, but does it poorly:
    #      It parses and serializes the whole document, which is expensive,
    #      then it frequently shoves `ins/del` tags in places they aren't
    #      allowed (e.g. as a child of a `<ul>`), which then causes a browser
    #      viewing the output to break elements up and destroy the rendering.
    #
    # The implementation below solves a bunch of these issues, but is still a
    # work in progress AND it needs to be implemented for
    # merge_speculative_deletions, too.


    # doc.extend(unbalanced_start)
    # if doc and not doc[-1].endswith(' '):
    #     # Fix up the case where the word before the insert didn't end with
    #     # a space
    #     doc[-1] += ' '
    # doc.append(f'<{tag_type}>')
    # if balanced and balanced[-1].endswith(' '):
    #     # We move space outside of </ins>
    #     balanced[-1] = balanced[-1][:-1]
    # doc.extend(balanced)
    # doc.append(f'</{tag_type}> ')
    # doc.extend(unbalanced_end)

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
                    if depth > 1:
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


def merge_speculative_deletions(change_chunks, doc):
    """
    Merge tokens that were deleted into a list of tokens (that represents the
    whole document) and surround them with markers that must later be replaced
    with HTML tags.

    This is used instead of `merge_changes` when the document *also* contains
    insertions. If a token was replaced, there may be duplicative HTML tags
    inserted (since they were attached to be the inserted and deleted tokens).
    The markers indicate areas that need cleanup sensitive to possible
    duplicated tags later.
    """
    return merge_delete(change_chunks, doc)


from lxml.html.diff import split_delete, NoDeletes, locate_unbalanced_start, locate_unbalanced_end


def cleanup_delete(chunks):
    """ Cleans up any DEL_START/DEL_END markers in the document, replacing
    them with <del></del>.  To do this while keeping the document
    valid, it may need to drop some tags (either start or end tags).

    It may also move the del into adjacent tags to try to move it to a
    similar location where it was originally located (e.g., moving a
    delete into preceding <div> tag, if the del looks like (DEL_START,
    'Text</div>', DEL_END)"""
    while 1:
        # Find a pending DEL_START/DEL_END, splitting the document
        # into stuff-preceding-DEL_START, stuff-inside, and
        # stuff-following-DEL_END
        try:
            pre_delete, delete, post_delete = split_delete(chunks)
        except NoDeletes:
            # Nothing found, we've cleaned up the entire doc
            break
        # The stuff-inside-DEL_START/END may not be well balanced
        # markup.  First we figure out what unbalanced portions there are:
        unbalanced_start, balanced, unbalanced_end = split_unbalanced(delete)
        # Then we move the span forward and/or backward based on these
        # unbalanced portions:
        locate_unbalanced_start(unbalanced_start, pre_delete, post_delete)
        locate_unbalanced_end(unbalanced_end, pre_delete, post_delete)
        doc = pre_delete
        if doc and not doc[-1].endswith(' '):
            # Fix up case where the word before us didn't have a trailing space
            doc[-1] += ' '

        # doc.extend(balanced)
        merge_changes(balanced, doc, 'del')

        doc.extend(post_delete)
        chunks = doc
    return chunks


def new_split_unbalanced(chunks):
    """Return (unbalanced_start, balanced, unbalanced_end), where each is
    a list of text and tag chunks.

    unbalanced_start is a list of all the tags that are opened, but
    not closed in this span.  Similarly, unbalanced_end is a list of
    tags that are closed but were not opened.  Extracting these might
    mean some reordering of the chunks."""
    start = []
    end = []
    tag_stack = []
    balanced = []
    for chunk in chunks:
        if not chunk.startswith('<'):
            balanced.append(chunk)
            continue
        endtag = chunk[1] == '/'
        name = chunk.split()[0].strip('<>/')
        if name in empty_tags:
            balanced.append(chunk)
            continue
        if endtag:
            if tag_stack and tag_stack[-1][0] == name:
                balanced.append(chunk)
                name, pos, tag = tag_stack.pop()
                balanced[pos] = tag
            elif tag_stack:
                start.extend([tag for name, pos, tag in tag_stack])
                tag_stack = []
                end.append(chunk)
            else:
                end.append(chunk)
        else:
            tag_stack.append((name, len(balanced), chunk))
            balanced.append(None)
    start.extend(
        [chunk for name, pos, chunk in tag_stack])
    balanced = [chunk for chunk in balanced if chunk is not None]
    return start, balanced, end
