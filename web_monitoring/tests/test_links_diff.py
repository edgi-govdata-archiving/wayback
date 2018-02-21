from pathlib import Path
from pkg_resources import resource_filename
import pytest
from web_monitoring.diff_errors import UndiffableContentError
from web_monitoring.links_diff import links_diff


def test_links_diff_only_includes_links():
    html_a = """
             Here is some HTML with <a href="http://google.com">some links</a>
             in it. Those links <a href="http://example.com">go places</a>.
             """
    html_b = """
             Here is some HTML with <a href="http://ugh.com">some</a> links
             in it. Those links <a href="http://example.com">go places</a>.
             """
    result = links_diff(html_a, html_b)['diff']
    assert 'Here is some' not in result
    assert '<li>go places' in result


def test_links_diff_only_has_outgoing_links():
    html_a = """
             Here is some HTML with <a href="http://google.com">some links</a>
             in it. Those links <a href="#local">go places</a>.
             """
    html_b = """
             Here is some HTML with <a href="http://google.com">some links</a>
             in it. Those links <a href="#local">go places</a>.
             """
    result = links_diff(html_a, html_b)['diff']
    assert result.count('<a') == 1


def test_links_diff_should_show_the_alt_text_for_images():
    html_a = """
             HTML with an <a href="http://google.com">
             <img src="whatever.jpg" alt="Alt text!"></a> image in it.
             Also an image with no alt text: <a href="/relative">
             <img src="whatever.jpg"></a>.
             """
    html_b = """
             HTML with an <a href="http://google.com">
             <img src="whatever.jpg" alt="Alt text!"></a> image in it.
             Also an image with no alt text: <a href="/relative">
             <img src="whatever.jpg"></a>.
             """
    result = links_diff(html_a, html_b)['diff']
    assert '[image: Alt text!]' in result
    assert '[image]' in result


def test_links_diff_should_raise_for_non_html_content():
    pdf_file = resource_filename('web_monitoring', 'example_data/empty.pdf')
    pdf_content = Path(pdf_file).read_text(errors='ignore')

    with pytest.raises(UndiffableContentError):
        links_diff(
            '<p>Just a little HTML</p>',
            pdf_content)


def test_links_diff_should_check_content_type_header():
    with pytest.raises(UndiffableContentError):
        links_diff(
            '<p>Just a little HTML</p>',
            'Some other text',
            a_headers={'Content-Type': 'text/html'},
            b_headers={'Content-Type': 'image/jpeg'})


def test_links_diff_should_not_check_content_type_header_if_content_type_options_is_nocheck():
    links_diff(
        '<p>Just a little HTML</p>',
        'Some other text',
        a_headers={'Content-Type': 'text/html'},
        b_headers={'Content-Type': 'image/jpeg'},
        content_type_options='nocheck')


def test_links_diff_should_not_raise_for_non_html_content_if_content_type_options_is_nosniff():
    pdf_file = resource_filename('web_monitoring', 'example_data/empty.pdf')
    pdf_content = Path(pdf_file).read_text(errors='ignore')

    links_diff(
        '<p>Just a little HTML</p>',
        pdf_content,
        content_type_options='nosniff')


def test_links_diff_should_not_check_content_if_content_type_options_is_ignore():
    pdf_file = resource_filename('web_monitoring', 'example_data/empty.pdf')
    pdf_content = Path(pdf_file).read_text(errors='ignore')

    links_diff(
        '<p>Just a little HTML</p>',
        pdf_content,
        a_headers={'Content-Type': 'text/html'},
        b_headers={'Content-Type': 'application/pdf'},
        content_type_options='ignore')
