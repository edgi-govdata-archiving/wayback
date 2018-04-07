from web_monitoring.cli import _filter_unchanged_versions


def test_filter_unchanged_versions():
    versions = (
        {'page_url': 'http://example.com', 'version_hash': 'a'},
        {'page_url': 'http://example.com', 'version_hash': 'b'},
        {'page_url': 'http://example.com', 'version_hash': 'b'},
        {'page_url': 'http://other.com',   'version_hash': 'b'},
        {'page_url': 'http://example.com', 'version_hash': 'b'},
        {'page_url': 'http://example.com', 'version_hash': 'c'},
        {'page_url': 'http://other.com',   'version_hash': 'd'},
        {'page_url': 'http://other.com',   'version_hash': 'b'},
    )

    assert list(_filter_unchanged_versions(versions)) == [
        {'page_url': 'http://example.com', 'version_hash': 'a'},
        {'page_url': 'http://example.com', 'version_hash': 'b'},
        {'page_url': 'http://other.com',   'version_hash': 'b'},
        {'page_url': 'http://example.com', 'version_hash': 'c'},
        {'page_url': 'http://other.com',   'version_hash': 'd'},
        {'page_url': 'http://other.com',   'version_hash': 'b'},
    ]
