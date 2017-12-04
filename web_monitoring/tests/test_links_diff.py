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
    result = links_diff(html_a, html_b)
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
    result = links_diff(html_a, html_b)
    assert result.count('<a') == 1


def test_links_diff_should_show_the_alt_text_for_images():
    html_a = """
             HTML with an <a href="http://google.com">
             <img src="whatever.jpg" alt="Alt text!"></a> image in it.
             """
    html_b = """
             HTML with an <a href="http://google.com">
             <img src="whatever.jpg" alt="Alt text!"></a> image in it.
             """
    result = links_diff(html_a, html_b)
    assert '[image: Alt text!]' in result
