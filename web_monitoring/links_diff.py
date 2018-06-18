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
        key=lambda link: link.text.lower())
    b_links = sorted(
        set([Link.from_element(element) for element in _find_outgoing_links(b_soup)]),
        key=lambda link: link.text.lower())

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
    soup = _assemble_html_diff(diff['diff'])

    # Add styling and metadata
    change_styles = soup.new_tag(
        'style',
        type='text/css',
        id='wm-diff-style')
    change_styles.string = """
        body { margin: 0; }
        ol { margin: 0; padding: 0; display: table; }
        li { opacity: 0.5; padding: 0.2em 1.5em; display: table-row; }
        li > * { display: table-cell; padding: 0.25em; vertical-align: middle; }
        li::before { content: "⚬"; display: table-cell; vertical-align: middle; width: 1.5em; text-align: center; }
        [wm-has-deletions],
        [wm-has-insertions] { opacity: 1; }
        [wm-has-deletions]::before,
        [wm-has-insertions]::before { content: "±"; }
        [wm-has-deletions], [wm-has-insertions] { background-color: #eee; }
        [wm-inserted] { background-color: #acf2bd; }
        [wm-inserted]::before { content: "+"; }
        [wm-deleted] { background-color: #fdb8c0; }
        [wm-deleted]::before { content: "-"; }
        ins { text-decoration: none; background-color: #acf2bd; }
        del { text-decoration: none; background-color: #fdb8c0; }
        .link-url a { line-break: loose; word-break: break-all; display: block; }"""
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


# FIXME: unify with _create_link_diff_listing
def _create_link_listing(link, soup, change_type=None):
    """
    Create an element to display in the list of links.
    """
    listing = soup.new_tag('li')
    tag_type = 'span'
    if change_type:
        if change_type == 'insertion':
            tag_type = 'ins'
            listing['wm-has-insertions'] = 'true'
            listing['wm-inserted'] = 'true'
        else:
            tag_type = 'del'
            listing['wm-has-deletions'] = 'true'
            listing['wm-deleted'] = 'true'

    text_tag = soup.new_tag(tag_type)
    text_tag['class'] = 'link-text'
    text_tag.append(link['text'])
    listing.append(text_tag)

    link_tag = soup.new_tag(tag_type)
    link_tag['class'] = 'link-url'
    url = link['href']
    url_link = soup.new_tag('a', href=url)
    url_link.string = f'({url})'
    link_tag.append(url_link)
    listing.append(link_tag)

    return listing


def _create_link_diff_listing(text_diff, href_diff, hrefs, soup):
    """
    Create an element to display in the list of links.
    """
    listing = soup.new_tag('li')

    # text = ''.join(map(_html_for_dmp_operation, text_diff))
    # listing.append(text + ' ')
    text_tag = soup.new_tag('span')
    text_tag['class'] = 'link-text'
    text_tag.append(''.join(map(_html_for_dmp_operation, text_diff)))
    listing.append(text_tag)

    link_insertions = filter(lambda operation: operation[0] >= 0, href_diff)
    link_deletions = filter(lambda operation: operation[0] <= 0, href_diff)
    link_tag = soup.new_tag('span')
    link_tag['class'] = 'link-url'
    listing.append(link_tag)

    url_text = ''.join(map(_html_for_dmp_operation, link_insertions))
    url_link = soup.new_tag('a', href=hrefs[1])
    url_link.string = f'({url_text})'
    link_tag.append(url_link)

    if hrefs[0] != hrefs[1]:
        url_text = ''.join(map(_html_for_dmp_operation, link_deletions))
        url_link = soup.new_tag('a', href=hrefs[0])
        url_link.string = f'({url_text})'
        link_tag.append(url_link)

    # link_text = ''.join(map(_html_for_dmp_operation, href_diff))
    # url_link = soup.new_tag('a', href=hrefs[1])
    # url_link.string = f'({link_text})'
    # listing.append(url_link)

    # if len(href_diff) > 1:
    #     original_link = soup.new_tag('a', href=hrefs[0])
    #     original_link.string = f'(original link)'
    #     listing.append(' ')
    #     listing.append(original_link)

    text_counts = Counter(map(lambda operation: operation[0], text_diff))
    href_counts = Counter(map(lambda operation: operation[0], href_diff))
    if text_counts[1] > 0 or href_counts[1] > 0:
        listing['wm-has-insertions'] = 'true'
    if text_counts[-1] > 0 or href_counts[-1] > 0:
        listing['wm-has-deletions'] = 'true'

    return listing


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
        if command == 'equal':
            for index, a_link in enumerate(a[a_start:a_end]):
                b_link = b[b_start + index]
                if hash(a_link) == hash(b_link):
                    yield (0, b_link.json())
                else:
                    text_diff = compute_dmp_diff(a_link.text, b_link.text)
                    href_diff = compute_dmp_diff(a_link.href, b_link.href)
                    yield (100, {
                        'text': text_diff,
                        'href': href_diff,
                        'hrefs': (a_link.href, b_link.href)
                    })

        if (command == 'insert' or command == 'replace'):
            for link in b[b_start:b_end]:
                yield (1, link.json())

        if (command == 'delete' or command == 'replace'):
            for link in a[a_start:a_end]:
                yield (-1, link.json())


def _assemble_html_diff(raw_diff):
    """
    Create a Beautiful Soup document representing a diff.

    Parameters
    ----------
    raw_diff : sequence
        The basic diff as a sequence of opcodes and links.
    """
    change_types = {-1: 'deletion', 0: None, 1: 'insertion'}
    result = _create_empty_soup()
    result_list = result.new_tag('ol')
    result.body.append(result_list)

    for code, link in raw_diff:
        if code == 100:
                result_list.append(_create_link_diff_listing(
                    link['text'],
                    link['href'],
                    link['hrefs'],
                    result))
        else:
            change_type = change_types[code]
            result_list.append(_create_link_listing(link, result, change_type))

    return result
