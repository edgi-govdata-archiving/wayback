from datetime import datetime, timezone
from .._models import CdxRecord, Memento
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

    assert record.raw_url == 'https://web.archive.org/web/19961231235847id_/http://www.nasa.gov/'
    assert record.view_url == 'https://web.archive.org/web/19961231235847/http://www.nasa.gov/'


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


def test_memento_repr():
    memento = Memento(
        url='https://www3.epa.gov/',
        timestamp=datetime(2022, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
        mode='id_',
        memento_url='https://web.archive.org/web/20221001000000id_/https://www3.epa.gov/',
        status_code=200,
        headers={},
        encoding='utf-8',
        raw=None,
        raw_headers={},
        links={},
        history=[],
        debug_history=[]
    )
    assert repr(memento) == '<wayback.Memento url="https://www3.epa.gov/" timestamp="2022-10-01T00:00:00+00:00">'
