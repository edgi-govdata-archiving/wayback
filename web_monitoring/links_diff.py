from bs4 import BeautifulSoup
from .content_type import raise_if_not_diffable_html
from .differs import compute_dmp_diff
from difflib import SequenceMatcher
from .html_diff_render import (get_title, _html_for_dmp_operation,
                               undiffable_content_tags)
import re


def links_diff(a_text, b_text, a_headers=None, b_headers=None,
               content_type_options='normal'):
    """
    Extracts all the outgoing links from a page and produces a diff of an
    HTML document that is simply a list of the text and URL of those links.

    It ignores links that merely navigate within the page.

    NOTE: this diff currently suffers from the fact that our diff server does
    not know the original URL of the content, so it can identify:
        <a href="#anchor-in-this-page">Text</a>
    as an internal link, but not:
        <a href="http://this.domain.com/this/page#anchor-in-this-page">Text</a>
    """
    raise_if_not_diffable_html(
        a_text,
        b_text,
        a_headers,
        b_headers,
        content_type_options)

    a_soup = BeautifulSoup(a_text, 'lxml')
    b_soup = BeautifulSoup(b_text, 'lxml')

    a_links = sorted(
        set([Link.from_element(element) for element in _find_outgoing_links(a_soup)]),
        key=lambda link: link.text.lower() + f'({link.href})')
    b_links = sorted(
        set([Link.from_element(element) for element in _find_outgoing_links(b_soup)]),
        key=lambda link: link.text.lower() + f'({link.href})')

    matcher = SequenceMatcher(a=a_links, b=b_links)
    opcodes = matcher.get_opcodes()
    diff = list(_assemble_diff(a_links, b_links, opcodes))

    return {
        'change_count': _count_changes(diff),
        'diff': diff,
        'a_parsed': a_soup,
        'b_parsed': b_soup
    }


def links_diff_json(a_text, b_text, a_headers=None, b_headers=None,
                    content_type_options='normal'):
    """
    Generate a diff of all outgoing links (see `links_diff()`) where the `diff`
    property is formatted as a list of change codes and values.
    """
    diff = links_diff(a_text, b_text, a_headers, b_headers,
                      content_type_options)
    return {
        'change_count': diff['change_count'],
        'diff': diff['diff']
    }


def links_diff_html(a_text, b_text, a_headers=None, b_headers=None,
                    content_type_options='normal'):
    """
    Generate a diff of all outgoing links (see `links_diff()`) where the `diff`
    property is an HTML string. Note the actual return type is still JSON.
    """
    diff = links_diff(a_text, b_text, a_headers, b_headers,
                      content_type_options)
    soup = _render_html_diff(diff['diff'])

    # Add styling and metadata
    change_styles = soup.new_tag(
        'style',
        type='text/css',
        id='wm-diff-style')
    change_styles.string = """
        body {
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            margin: 0;
        }
        .links-list {
            border-collapse: collapse;
            table-layout: fixed;
            width: 100%;
        }
        .links-list th {
            background: #f6f6f6;
            border-bottom: 1px solid #ccc;
            padding: 0.25em;
            text-align: left;
        }
        .links-list > tbody > tr:first-child > td {
            padding-top: 0.5em;
        }
        .links-list--item > td {
            border-bottom: 1px solid #fff;
            opacity: 0.5;
            padding: 0.25em;
        }
        .links-list--change-type-col {
            width: 1.5em;
        }
        .links-list--text-col,
        .links-list--href-col {
            width: 50%;
        }
        .links-list--href a {
            line-break: loose;
            word-break: break-all;
        }
        [wm-has-deletions] > td,
        [wm-has-insertions] > td {
            background-color: #eee;
            opacity: 1;
        }
        [wm-inserted] > td { background-color: #acf2bd; }
        [wm-deleted] > td  { background-color: #fdb8c0; }
        ins { text-decoration: none; background-color: #acf2bd; }
        del { text-decoration: none; background-color: #fdb8c0; }"""
    soup.head.append(change_styles)
    soup.title.string = get_title(diff['b_parsed'])

    return {
        'change_count': diff['change_count'],
        'diff': soup.prettify(formatter=None)
    }


class Link:
    """
    Represents a link that was used on the page. Designed to be fed into
    SequenceMatcher for diffing.

    Note that Link objects have a very loose sense of equality. That is:

        link_a == link_b

    only indicates that link_a and link_b may be sorta kinda be representing
    the same thing, but that you should still compare them in a more nuanced
    way. To check for strict equality, use their hashes:

        hash(link_a) == hash(link_b)
    """

    @classmethod
    def from_element(cls, element):
        """
        Create a Link from a Beautiful Soup `<a>` element
        """
        return cls(element['href'], _get_link_text(element))

    def __init__(self, href, text):
        # TODO: add a `url` so we can differentiate the href and the actual
        # target of the link (in the case of paths rather than URLs)
        # This requires knowing the base origin and path for the link.
        self.href = self._clean_href(href)
        self.text = text.strip()

    def __hash__(self):
        return hash((self.href, self.text.lower()))

    def __eq__(self, other):
        # This is actually a "rough" equality check -- trying to get a sense
        # of whether two links are the same "thing" even if they have
        # internal differences in their text or href.
        return self.href == other.href or self.text.lower() == other.text.lower()

    def json(self):
        return {'text': self.text, 'href': self.href}

    def _clean_href(self, href):
        origin_match = re.match(r'^([\w+\-]+:)?//[^/]+', href)
        if origin_match:
            return origin_match.group(0).lower() + href[origin_match.end(0):]
        return href


def _find_outgoing_links(soup):
    """
    Yields each of the `<a>` elements in a Beautiful Soup document that point
    to other pages.
    """
    for link in soup.find_all('a'):
        href = link.get('href')
        if href and not href.startswith('#'):
            yield link


def _get_link_text(link):
    """
    Get the "text" to diff and display for an `<a>` element.
    """
    # The content of tags like <script> and <style> shows up in the `.text`
    # attribute, so just go ahead and remove them from the DOM
    for invisible_tag in link.find_all(undiffable_content_tags):
        invisible_tag.extract()

    for image in link.find_all('img'):
        alt = image.get('alt')
        if alt:
            image.replace_with(f'[image: {alt}]')
        else:
            image.replace_with('[image]')

    text = link.text.strip()
    if not text:
        if link.has_attr('title'):
            text = f'[tooltip: {link["title"]}]'
        else:
            text = '[no text]'

    return text


def _count_changes(opcodes):
    return len([operation for operation in opcodes if operation[0] != 0])


def _assemble_diff(a, b, opcodes):
    """
    Yield each link in the diff with a code for addition (1), removal (-1),
    unchanged (0), or nested diff (100).

    Parameters
    ----------
    a : list
        The list of links in the previous verson of a document.
    b : list
        The list of links in the new version of a document.
    opcodes : list
        List of opcodes from SequenceMatcher that defines what to do with each
        item in the lists of links.
    """
    # If we have the lists:
    #    A                             B
    #    --------------------------- | ------------------------------
    # 1. "Pony time!" ponytime.com/a | "Pony time!" ponytime.com/b
    # 2. "Pony time!" ponytime.com/b | "Donkey time." not-ponies.com/
    #
    # SequenceMatcher can wind up putting the first row together as equal, but
    # then sectioning off the second row as deleted from A. That's because the
    # links in the first row qualify as "roughly" equal, which is equal as far
    # as SequenceMatcher is allowed to know. Unfortunately, that prevents it
    # from correctly identifying that A2 + B1 are actually the ones that are
    # the same and A1 is the one that should be marked as gone. We need to do a
    # first pass to move any insertions or deletions that are exactly equal to
    # a link in the adjacent set SequenceMatcher marked as equal into that
    # equal set. (Note this also means our equal set handling below will have
    # to account for A having more items than B or vice-versa, which couldn't
    # happen before.)
    operation_count = len(opcodes)
    for index, operation in enumerate(opcodes):
        command = operation[0]
        if command == 'equal':
            continue

        last_equal = None
        next_equal = None
        if index > 0 and opcodes[index - 1][0] == 'equal':
            last_equal = a[opcodes[index - 1][2] - 1]
        if index + 1 < operation_count and opcodes[index + 1][0] == 'equal':
            next_equal = a[opcodes[index + 1][1]]

        if (command == 'insert' or command == 'replace'):
            for link_index, link in enumerate(b[operation[3]:operation[4]]):
                # FIXME: really we should stop looking for last_equal after
                # finding a non-equal one... this implementatin assumes (I
                # *think* correctly, but not with total confidence) that equal
                # items will always be lined up on one side or the other of the
                # added/removed content.
                if last_equal and last_equal == link:
                    # opcodes are tuples, so we can't just edit them.
                    last_op = opcodes[index - 1]
                    opcodes[index - 1] = (last_op[0], last_op[1], last_op[2], last_op[3], last_op[4] + 1)
                    opcodes[index] = (operation[0], operation[1], operation[2], operation[3] + 1, operation[4])
                elif next_equal and next_equal == link:
                    # opcodes are tuples, so we can't just edit them.
                    next_op = opcodes[index + 1]
                    opcodes[index] = (operation[0], operation[1], operation[2], operation[3], operation[4] - 1)
                    opcodes[index + 1] = (next_op[0], next_op[1], next_op[2], next_op[3] - 1, next_op[4])

        if (command == 'delete' or command == 'replace'):
            for link_index, link in enumerate(a[operation[1]:operation[2]]):
                # FIXME: really we should stop looking for last_equal after
                # finding a non-equal one... this implementatin assumes (I
                # *think* correctly, but not with total confidence) that equal
                # items will always be lined up on one side or the other of the
                # added/removed content.
                if last_equal and last_equal == link:
                    # opcodes are tuples, so we can't just edit them.
                    last_op = opcodes[index - 1]
                    opcodes[index - 1] = (last_op[0], last_op[1], last_op[2] + 1, last_op[3], last_op[4])
                    opcodes[index] = (operation[0], operation[1] + 1, operation[2], operation[3], operation[4])
                elif next_equal and next_equal == link:
                    # opcodes are tuples, so we can't just edit them.
                    next_op = opcodes[index + 1]
                    opcodes[index] = (operation[0], operation[1], operation[2] - 1, operation[3], operation[4])
                    opcodes[index + 1] = (next_op[0], next_op[1] - 1, next_op[2], next_op[3], next_op[4])

    for command, a_start, a_end, b_start, b_end in opcodes:
        # The equality comparator for links only tells us whether links were
        # "roughly" equal -- so two links that SequenceMatcher told us were the
        # same may internal differences we need to display (this is by design).
        if command == 'equal':
            # This is a bit tricky: there might be several roughly equal links
            # in a row, where some are exactly equal, but their order is
            # shuffled around. We want to match up all the exactly equal ones.
            a_remainders = []
            a_set = a[a_start:a_end]
            b_set = b[b_start:b_end]
            last_index = a_end - 1 - a_start
            for index, a_link in enumerate(a_set):
                # Look for a B version link that was exactly equal to the
                # current A version link.
                for b_index, b_link in enumerate(b_set):
                    if hash(a_link) == hash(b_link):
                        del b_set[b_index]
                        yield (0, b_link.json())
                        break
                # If we didn't find an exact match, set this A link aside.
                else:
                    a_remainders.append(a_link)

                # If we're at the end of the list or the next link is not
                # roughly equal, go back through the links that were set aside
                # and generate a sub-diff for each of them.
                if index == last_index or a_link != a_set[index + 1]:
                    for a_link in a_remainders:
                        # b_set may contain more items at the end that are not
                        # roughly equal (see how we disbalanced this group in
                        # the first pass over the opcodes above), so we need
                        # to check that the items match before diffing inside.
                        if b_set and b_set[0] == a_link:
                            b_link = b_set[0]
                            del b_set[0]
                            text_diff = compute_dmp_diff(a_link.text, b_link.text)
                            href_diff = compute_dmp_diff(a_link.href, b_link.href)
                            yield (100, {
                                'text': text_diff,
                                'href': href_diff,
                                'hrefs': (a_link.href, b_link.href)
                            })
                        else:
                            yield (-1, a_link.json())

                    while b_set and b_set[0] == a_link:
                        yield (1, b_set[0].json())
                        del b_set[0]

                    a_remainders.clear()

            # Handle any left over additions
            for b_link in b_set:
                yield (1, b_link.json())

        if (command == 'insert' or command == 'replace'):
            for link in b[b_start:b_end]:
                yield (1, link.json())

        if (command == 'delete' or command == 'replace'):
            for link in a[a_start:a_end]:
                yield (-1, link.json())


# HTML DIFF RENDERING -----------------------------------------------------

def _create_empty_soup(title=''):
    """
    Creates a Beautiful Soup document representing an empty HTML page.

    Parameters
    ----------
    title : string
        The new document's title.
    """
    return BeautifulSoup(f"""<!doctype html>
        <html>
            <head>
                <meta charset="utf-8">
                <title>{title}</title>
            </head>
            <body>
            </body>
        </html>
        """, 'lxml')


def not_deleted(diff_item):
    return diff_item[0] >= 0


def not_inserted(diff_item):
    return diff_item[0] <= 0


def _html_for_text_diff(diff):
    return ''.join(map(_html_for_dmp_operation, diff))


def _tag(soup, name, attributes=None, *children):
    """
    Build tags in a quicker, more composable way. Also lets you use 'class'
    attributes without a lot of extra rigamarole.
    """
    tag = soup.new_tag(name)
    if attributes:
        for key, value in attributes.items():
            # Remove boolean attributes that are False
            if value is not None and value is not False:
                tag[key] = value

    for child in children:
        tag.append(child)

    return tag


def _tagger(soup):
    def tagger(*args, **kwargs):
        return _tag(soup, *args, **kwargs)
    return tagger


CHANGE_INFO = {
    -1:  {'symbol': '-', 'title': 'Deleted'},
    0:   {'symbol': '⚬', 'title': None},
    1:   {'symbol': '+', 'title': 'Added'},
    100: {'symbol': '±', 'title': 'Changed'},
}


def _table_row_for_link(soup, change_type, link):
    tag = _tagger(soup)
    row = tag('tr', {
        'class': 'links-list--item',
        'wm-has-insertions': change_type > 0,
        'wm-inserted': change_type == 1,
        'wm-has-deletions': change_type < 0 or change_type == 100,
        'wm-deleted': change_type == -1,
    })

    change = CHANGE_INFO[change_type] or CHANGE_INFO[0]
    row.append(tag('td', {
        'class': 'links-list--change-type',
        'title': change['title'],
    }, change['symbol']))

    text_cell = tag('td', {'class': 'links-list--text'})
    row.append(text_cell)
    if change_type == 100:
        text_insertions = filter(not_deleted, link['text'])
        text_cell.append(_html_for_text_diff(text_insertions))
        if len(link['text']) != 1:
            text_cell.append(tag('br'))
            text_deletions = filter(not_inserted, link['text'])
            text_cell.append(_html_for_text_diff(text_deletions))
    else:
        text_cell.append(link['text'])

    href_cell = tag('td', {'class': 'links-list--href'})
    row.append(href_cell)
    if change_type == 100:
        href_insertions = filter(not_deleted, link['href'])
        url_text = _html_for_text_diff(href_insertions)
        url = link['hrefs'][1]
        href_cell.append(tag('a', {'href': url}, f'({url_text})'))

        if link['hrefs'][0] != link['hrefs'][1]:
            href_cell.append(tag('br'))
            href_deletions = filter(not_inserted, link['href'])
            url_text = _html_for_text_diff(href_deletions)
            url = link['hrefs'][0]
            href_cell.append(tag('a', {'href': url}, f'({url_text})'))
    else:
        url = link['href']
        href_cell.append(tag('a', {'href': url}, f'({url})'))

    return row


def _render_html_diff(raw_diff):
    """
    Create a Beautiful Soup document representing a diff.

    Parameters
    ----------
    raw_diff : sequence
        The basic diff as a sequence of opcodes and links.
    """
    result = _create_empty_soup()
    tag = _tagger(result)
    result.body.append(
        tag('table', {'class': 'links-list'},
            tag('col', {'class': 'links-list--change-type-col'}),
            tag('col', {'class': 'links-list--text-col'}),
            tag('col', {'class': 'links-list--href-col'}),
            tag('thead', {},
                tag('tr', {},
                    tag('th'),
                    tag('th', {}, 'Link Text'),
                    tag('th', {}, 'URL'))),
            tag('tbody', {}, *(
                _table_row_for_link(result, code, link)
                for code, link in raw_diff))))

    return result
