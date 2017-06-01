import web_monitoring.pf_edgi as wp

# randomly chosen real examples -- might need to be updated if these are ever
# moved or removed
cabinet = 'J_004232364409_3994fe0dd66ddd779'
archive = 1494957042
page_key = '6cd06af38650d4243b3c5da03bce8dca0df653b3062e2e642e502e89905e4f0a'
# 'page_key' just means file ID -- this is *not* a sensitive key

def test_list_cabinets():
    cabinets = wp.list_cabinets()
    assert cabinet in cabinets


def test_list_archives():
    archives = wp.list_archives(cabinet)
    # An archive's timestamp is its ID.
    timestamps = [a['timestamp'] for a in archives]
    assert archive in timestamps


def test_load_archive():
    result = wp.load_archive(cabinet, archive)
    assert result['desc'] in ('loaded', 'already_loaded')
    result = wp.unload_archive(cabinet, archive)
    assert result['desc'] == 'unloaded'


def test_search():
    # ensure archive is loaded
    result = wp.load_archive(cabinet, archive)
    assert result['desc'] in ('loaded', 'already_loaded')

    result = wp.search_archive(cabinet, archive, 'html')
    assert 'founds' in result


def test_get_file():
    # ensure archive is loaded
    result = wp.load_archive(cabinet, archive)
    assert result['desc'] in ('loaded', 'already_loaded')

    result = wp.get_file_metadata(cabinet, archive, page_key)
    # basic inspection to make sure this is what we think it is
    assert 'file' in result
    assert 'Links' in result['file']
    assert 'Header' in result['file']

    result = wp.get_file(cabinet, archive, page_key)
    assert b'Information related to the GES DISC' in result
