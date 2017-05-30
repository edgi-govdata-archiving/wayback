# Command Line Interface
# See scripts/ directory for associated executable(s). All of the interesting
# functionality is implemented in this module to make it easier to test.
from docopt import docopt
from tqdm import tqdm
from web_monitoring import internetarchive as ia
from web_monitoring import pf_edgi as pf
from web_monitoring import db


# These functions lump together library code into monolithic operations for the
# CLI. They also print. To access this functionality programmatically, it is
# better to use the underlying library code.


def import_ia(url, agency, site):
    print('obtaining versions list from Internet Archive...')
    versions = ia.list_versions(url)
    # Collect all the results and POST them as a unit (rather than streaming).
    formatted_versions = []
    for dt, uri in tqdm(versions, desc='formatting versions'):
        version = ia.timestamped_uri_to_version(dt, uri,
                                                url=url,
                                                site=site,
                                                agency=agency)
        formatted_versions.append(version)
    print('posting to db....')
    db.post_to_db(formatted_versions)


def import_pf_archive(cabinet_id, archive_id, *, agency, site):
    formatted_versions = []
    for version in tqdm(pf.archive_to_versions(cabinet_id, archive_id,
                                               agency=agency, site=site),
                        desc='formatting versions'):
        formatted_versions.append(version)
    print('posting to db....')
    db.post_to_db(formatted_versions)


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
