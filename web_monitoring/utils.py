import io
import lxml.html


def extract_title(content_bytes):
    "Return content of <title> tag as string."
    content_as_file = io.StringIO(content_bytes.decode(errors='ignore'))
    title = lxml.html.parse(content_as_file).find(".//title").text
    return title
