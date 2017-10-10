# Command Line Interface
# See scripts/ directory for associated executable(s). All of the interesting
# functionality is implemented in this module to make it easier to test.
from docopt import docopt
import pandas
from tqdm import tqdm
from web_monitoring import db
from web_monitoring import internetarchive as ia
from web_monitoring import pf_edgi as pf


# These functions lump together library code into monolithic operations for the
# CLI. They also print. To access this functionality programmatically, it is
# better to use the underlying library code.


def import_ia(url, agency, site, from_date=None, to_date=None):
    cli = db.Client.from_env()  # will raise in env vars not set
    # Pulling on this generator does the work.
    versions = (ia.timestamped_uri_to_version(version.date, version.raw_url,
                                              url=version.url,
                                              site=site,
                                              agency=agency,
                                              view_url=version.view_url)
                for version in ia.list_versions(url,
                                                from_date=from_date,
                                                to_date=to_date))
    # Wrap it in a progress bar.
    versions = tqdm(versions, desc='importing', unit=' versions')
    print('Submitting Versions to web-monitoring-db...')
    import_ids = cli.add_versions_batched(versions)
    print('Import jobs IDs: {}'.format(import_ids))
    print('Polling web-monitoring-db until import jobs are finished...')
    errors = cli.monitor_batch_import_status(import_ids)
    if errors:
        print("Errors: {}".format(errors))


def import_pf_archive(cabinet_id, archive_id, *, agency, site):
    cli = db.Client.from_env()  # will raise in env vars not set
    # Pulling on this generator does the work.
    versions = pf.archive_to_versions(cabinet_id, archive_id,
                                      agency=agency,
                                      site=site)
    # Wrap it in a progress bar.
    versions = tqdm(versions, desc='importing', unit=' versions')
    print('Submitting Versions to web-monitoring-db...')
    import_ids = cli.add_versions_batched(versions)
    print('Import jobs IDs: {}'.format(import_ids))
    print('Polling web-monitoring-db until import jobs are finished...')
    errors = cli.monitor_batch_import_status(import_ids)
    if errors:
        print("Errors: {}".format(errors))


def parse_date_argument(date_string):
    """Parse a CLI argument that should represent a date into a datetime"""
    if not date_string:
        return None

    try:
        parsed = pandas.to_datetime(date_string)
        if not pandas.isnull(parsed):
            return parsed
    except ValueError:
        pass

    return None


def main():
    doc = """Command Line Interface to the web_monitoring Python package

Usage:
wm import ia <url> --site <site> --agency <agency>
             [--from <from_date>]
             [--to <to_date>]
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
                      site=arguments['<site>'],
                      from_date=parse_date_argument(arguments['<from_date>']),
                      to_date=parse_date_argument(arguments['<to_date>']))
        elif arguments['pf']:
            import_pf_archive(cabinet_id=arguments['<cabinet_id>'],
                              archive_id=arguments['<archive_id>'],
                              agency=arguments['<agency>'],
                              site=arguments['<site>'])
