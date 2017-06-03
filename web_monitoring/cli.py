# Command Line Interface
# See scripts/ directory for associated executable(s). All of the interesting
# functionality is implemented in this module to make it easier to test.
from docopt import docopt
import time
import toolz
from tqdm import tqdm
import sys
from web_monitoring import internetarchive as ia
from web_monitoring import pf_edgi as pf
from web_monitoring import db


# These functions lump together library code into monolithic operations for the
# CLI. They also print. To access this functionality programmatically, it is
# better to use the underlying library code.


def import_ia(url, agency, site):
    # Pulling on this generator does the work.
    versions = (ia.timestamped_uri_to_version(dt, uri,
                                              url=url,
                                              site=site,
                                              agency=agency)
                for dt, uri in ia.list_versions(url))
    # Wrap it in a progress bar.
    versions = tqdm(versions, desc='importing', unit=' versions')
    return post_versions_batched(versions)


def import_pf_archive(cabinet_id, archive_id, *, agency, site):
    # Pulling on this generator does the work.
    versions = pf.archive_to_versions(cabinet_id, archive_id,
                                      agency=agency,
                                      site=site)
    # Wrap it in a progress bar.
    versions = tqdm(versions, desc='importing', unit=' versions')
    return post_versions_batched(versions)


def post_versions_batched(versions):
    # POST to the server in chunks. Stash the import id from each response.
    BATCH_SIZE = 1000
    import_ids = []
    error_tally = 0
    success_tally = 0
    for batch in toolz.partition_all(BATCH_SIZE, versions):
        formatted_versions = list(batch)  # processing happens here
        success_tally += len(formatted_versions)
        res = db.post_versions(formatted_versions)
        assert res.ok
        import_ids.append(res.json()['data']['id'])

    # Poll the server until all import jobs are complete. Print and tally any
    # processing errors.
    print("Done. Now polling server, monitoring for job completition...")
    try:
        while True:
            if not import_ids:
                # All are done
                break
            for import_id in tuple(import_ids):
                res = db.query_import_status(import_id)
                assert res.ok
                data = res.json()['data']
                if data['status'] == 'complete':
                    for error in data['processing_errors']:
                        print('Server reported processing error:', error)
                        success_tally -= 1
                        error_tally += 1
                    import_ids.remove(import_id)
            time.sleep(1)
    except KeyboardInterrupt:
        # Killed before the server reported success
        print("The process was interrupted after job submission was complete "
              "but before the server reported job completion. The outstanding "
              "jobs have ids: {}".format(import_ids))
        sys.exit(0)
    print("Completed {} versions succcessfully. There were {} errors."
          "".format(success_tally, error_tally))


def main():
    doc = """Command Line Interface to the web_monitoring Python package

Usage:
wm import ia <url> --site <site> --agency <agency>
wm import pf <cabinet_id> <archive_id> --site <site> --agency <agency>

Options:
-h --help     Show this screen.
--version     Show version.
"""
    arguments = docopt(doc, version='0.0.1')
    if arguments['import']:
        if arguments['ia']:
            import_ia(url=arguments['<url>'],
                      agency=arguments['<agency>'],
                      site=arguments['<site>'])
        elif arguments['pf']:
            import_pf_archive(cabinet_id=arguments['<cabinet_id>'],
                              archive_id=arguments['<archive_id>'],
                              agency=arguments['<agency>'],
                              site=arguments['<site>'])
