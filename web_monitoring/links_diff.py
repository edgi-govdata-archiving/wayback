from bs4 import BeautifulSoup
from .content_type import raise_if_not_diffable_html
from difflib import SequenceMatcher
from .html_diff_render import get_title


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

    soup_old = BeautifulSoup(a_text, 'lxml')
    soup_new = BeautifulSoup(b_text, 'lxml')

    old_links = sorted(
        set([Link.from_element(element) for element in _find_outgoing_links(soup_old)]),
        key=lambda link: link.text.lower())
    new_links = sorted(
        set([Link.from_element(element) for element in _find_outgoing_links(soup_new)]),
        key=lambda link: link.text.lower())

    matcher = SequenceMatcher(a=old_links, b=new_links)
    opcodes = matcher.get_opcodes()
    change_count = _count_changes(opcodes)
    soup = _assemble_diff(old_links, new_links, opcodes)

    change_styles = soup.new_tag(
        'style',
        type='text/css',
        id='wm-diff-style')
    change_styles.string = """
        ins {text-decoration: none; background-color: #d4fcbc;}
        del {text-decoration: none; background-color: #fbb6c2;}"""
    soup.head.append(change_styles)
    soup.title.string = get_title(soup_new)

    return {
        'change_count': change_count,
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
        self.href = href
        self.text = text.strip()

    def __hash__(self):
        # TODO: compare lower-cased origin for href part
        return hash((self.href, self.text.lower()))

    def __eq__(self, other):
        return self.href == other.href and self.text == other.text


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


def _create_link_listing(link, soup, wrap=None):
    """
    Create an element to display in the list of links.
    """
    listing = soup.new_tag('li')
    container = wrap or listing

    container.append(link.text + ' ')

    url_link = soup.new_tag('a', href=link.href)
    url_link.string = f'({link.href})'
    container.append(url_link)

    if wrap:
        listing.append(wrap)

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
    return len([operation for operation in opcodes if operation[0] != 'equal'])


def _assemble_diff(a, b, opcodes):
    """
    Create a Beautiful Soup document representing a diff.

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
    result = _create_empty_soup()
    result_list = result.new_tag('ul')
    result.body.append(result_list)

    for command, a_start, a_end, b_start, b_end in opcodes:
        if command == 'equal':
            for link in b[b_start:b_end]:
                result_list.append(_create_link_listing(link, result))

        if (command == 'insert' or command == 'replace'):
            for link in b[b_start:b_end]:
                result_list.append(_create_link_listing(
                    link,
                    result,
                    wrap=result.new_tag('ins')))

        if (command == 'delete' or command == 'replace'):
            for link in a[a_start:a_end]:
                result_list.append(_create_link_listing(
                    link,
                    result,
                    wrap=result.new_tag('del')))

    return result
