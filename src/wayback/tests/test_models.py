from datetime import datetime, timezone
from .._models import CdxRecord
import pytest


def test_cdx_record_urls():
    record = CdxRecord(
        urlkey='org,nasa)/',
        timestamp=datetime(1996, 12, 31, 23, 58, 47, tzinfo=timezone.utc),
        original='http://www.nasa.gov/',
        mimetype='text/html',
        statuscode=200,
        digest='ABC',
        length=100
    )

    # raw_url should have 'id_' mode
    expected_raw = 'https://web.archive.org/web/19961231235847id_/http://www.nasa.gov/'
    assert record.raw_url == expected_raw

    # view_url should have no mode suffix
    expected_view = 'https://web.archive.org/web/19961231235847/http://www.nasa.gov/'
    assert record.view_url == expected_view


def test_cdx_record_deprecated_fields():
    record = CdxRecord(
        urlkey='org,nasa)/',
        timestamp=datetime(1996, 12, 31, 23, 58, 47, tzinfo=timezone.utc),
        original='http://www.nasa.gov/',
        mimetype='text/html',
        statuscode=200,
        digest='ABC',
        length=100
    )

    with pytest.warns(DeprecationWarning, match='key'):
        assert record.key == 'org,nasa)/'
    with pytest.warns(DeprecationWarning, match='url'):
        assert record.url == 'http://www.nasa.gov/'
    with pytest.warns(DeprecationWarning, match='mime_type'):
        assert record.mime_type == 'text/html'
    with pytest.warns(DeprecationWarning, match='status_code'):
        assert record.status_code == 200
