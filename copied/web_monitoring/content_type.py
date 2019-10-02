# Tools for checking the type of content and making sure it's acceptable for
# a given diffing algorithm

import re
from .diff_errors import UndiffableContentError

# Matches content strings that are probably not HTML.
# See also https://dev.w3.org/html5/cts/html5-type-sniffing.html and
# https://mimesniff.spec.whatwg.org/#rules-for-identifying-an-unknown-mime-type
NON_HTML_PATTERN = re.compile(r'^[\s\n\r]*(%s)' % '|'.join((
    # PDF
    r'%PDF-',
    # PostScript
    r'%!PS-Adobe-',
    # Various types of GIF
    r'GIF87a',
    r'GIF89a',
    # BMP images
    r'BM',
    # JPG images
    r'\u0089\u0050\u004E\u0047\u000D\u000A\u001A\u000A|\u00FF\u00D8\u00FF',
)))

# Content Types that we know represent HTML
ACCEPTABLE_CONTENT_TYPES = (
    'application/html',
    'application/xhtml',
    'application/xhtml+xml',
    'application/xml',
    'application/xml+html',
    'application/xml+xhtml',
    'text/webviewhtml',
    'text/html',
    'text/x-server-parsed-html',
    'text/xhtml',
)

# Matches Content Types that *could* be acceptable for diffing as HTML
UNKNOWN_CONTENT_TYPE_PATTERN = re.compile(r'^(%s)$' % '|'.join((
    r'application/octet-stream',
    r'text/.+'
)))


def is_not_html(text, headers=None, check_options='normal'):
    """
    Determine whether a string is not HTML. In general, this errs on the side
    of leniency; it should have few false positives, but many false negatives.

    Parameters
    ----------
    text : string
        Potential HTML content string
    headers : dict
        Any HTTP headers associated with the text
    check_options : string
        Control content type detection. Options are:
        - `normal` uses the `Content-Type` header and then falls back to
          sniffing to determine content type.
        - `nocheck` ignores the `Content-Type` header but still sniffs.
        - `nosniff` uses the `Content-Type` header but does not sniff.
        - `ignore` doesn’t do any checking at all.
    """
    if headers and (check_options == 'normal' or check_options == 'nosniff'):
        content_type = headers.get('Content-Type', '').split(';', 1)[0].strip()
        if content_type:
            if content_type in ACCEPTABLE_CONTENT_TYPES:
                return False
            elif not UNKNOWN_CONTENT_TYPE_PATTERN.match(content_type):
                return True

    if check_options == 'normal' or check_options == 'nocheck':
        stripped = text.lstrip()
        return bool(NON_HTML_PATTERN.match(stripped))

    return False


def raise_if_not_diffable_html(a_text, b_text, a_headers=None, b_headers=None,
                               content_type_options='normal'):
    """
    Determine whether two strings are both HTML and raise a useful exception
    if not. In general, this errs on the side of leniency.

    Parameters
    ----------
    a_text : string
        Source HTML of one document to compare
    b_text : string
        Source HTML of the other document to compare
    a_headers : dict
        Any HTTP headers associated with the `a` document
    b_headers : dict
        Any HTTP headers associated with the `b` document
    content_type_options : string
        Control content type detection. Options are:
        - `normal` uses the `Content-Type` header and then falls back to
          sniffing to determine content type.
        - `nocheck` ignores the `Content-Type` header but still sniffs.
        - `nosniff` uses the `Content-Type` header but does not sniff.
        - `ignore` doesn’t do any checking at all.
    """
    html_error_a = is_not_html(a_text, a_headers, content_type_options)
    html_error_b = is_not_html(b_text, b_headers, content_type_options)
    if html_error_a and html_error_b:
        raise UndiffableContentError('`a` and `b` are not HTML documents')
    elif html_error_a:
        raise UndiffableContentError('`a` is not an HTML document')
    elif html_error_b:
        raise UndiffableContentError('`b` is not an HTML document')
