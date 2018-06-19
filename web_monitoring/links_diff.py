from bs4 import BeautifulSoup
from .content_type import raise_if_not_diffable_html
from collections import Counter
from .differs import compute_dmp_diff
from difflib import SequenceMatcher
from .html_diff_render import get_title, _html_for_dmp_operation
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
        }
        .links-list--item > td {
            border-bottom: 1px solid #fff;
            opacity: 0.5;
            padding: 0.25em;
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
    for image in link.find_all('img'):
        alt = image.get('alt')
        if alt:
            image.replace_with(f'[image: {alt}]')
        else:
            image.replace_with('[image]')
    return link.text


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
                        b_link = b_set[0]
                        del b_set[0]
                        text_diff = compute_dmp_diff(a_link.text, b_link.text)
                        href_diff = compute_dmp_diff(a_link.href, b_link.href)
                        yield (100, {
                            'text': text_diff,
                            'href': href_diff,
                            'hrefs': (a_link.href, b_link.href)
                        })
                    a_remainders.clear()

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


def _tag(soup, name, attributes, *children):
    tag = soup.new_tag(name)
    # Remove boolean attributes that are False
    for key, value in attributes.items():
        if value is not None and value != False:
            tag[key] = value
    for child in children:
        tag.append(child)
    return tag


CHANGE_INFO = {
    -1:  {'symbol': '-', 'title': 'Deleted'},
    0:   {'symbol': '⚬', 'title': None},
    1:   {'symbol': '+', 'title': 'Added'},
    100: {'symbol': '±', 'title': 'Changed'},
}


def _table_row_for_link(soup, change_type, link):
    row = _tag(soup, 'tr', {
        'class': 'links-list--item',
        'wm-has-insertions': change_type > 0,
        'wm-inserted': change_type == 1,
        'wm-has-deletions': change_type < 0 or change_type == 100,
        'wm-deleted': change_type == -1,
    })

    change = CHANGE_INFO[change_type] or CHANGE_INFO[0]
    row.append(_tag(soup, 'td', {
        'class': 'links-list--change-type',
        'title': change['title'],
    }, change['symbol']))

    text_cell = _tag(soup, 'td', {'class': 'links-list--text'})
    row.append(text_cell)
    if change_type == 100:
        text_insertions = filter(not_deleted, link['text'])
        text_cell.append(_html_for_text_diff(text_insertions))
        if len(link['text']) != 1:
            text_cell.append(soup.new_tag('br'))
            text_deletions = filter(not_inserted, link['text'])
            text_cell.append(_html_for_text_diff(text_deletions))
    else:
        text_cell.append(link['text'])

    href_cell = _tag(soup, 'td', {'class': 'links-list--href'})
    row.append(href_cell)
    if change_type == 100:
        href_insertions = filter(not_deleted, link['href'])
        url_text = _html_for_text_diff(href_insertions)
        url = link['hrefs'][1]
        href_cell.append(_tag(soup, 'a', {'href': url}, f'({url_text})'))

        if link['hrefs'][0] != link['hrefs'][1]:
            href_cell.append(soup.new_tag('br'))
            href_deletions = filter(not_inserted, link['href'])
            url_text = _html_for_text_diff(href_deletions)
            url = link['hrefs'][0]
            href_cell.append(_tag(soup, 'a', {'href': url}, f'({url_text})'))
    else:
        url = link['href']
        href_cell.append(_tag(soup, 'a', {'href': url}, f'({url})'))

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
    result.body.append(
        _tag(result, 'table', {'class': 'links-list'},
             _tag(result, 'tbody', {}, *(
                  _table_row_for_link(result, code, link)
                  for code, link in raw_diff))))

    return result
