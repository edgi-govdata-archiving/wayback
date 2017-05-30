import io
import lxml.html


def extract_title(content_bytes):
    "Return content of <title> tag as string. On failure return empty string."
    content_as_file = io.StringIO(content_bytes.decode(errors='ignore'))
    try:
        title = lxml.html.parse(content_as_file).find(".//title")
    except Exception:
        return ''
    if title is None:
        return ''
    else:
        return title.text
