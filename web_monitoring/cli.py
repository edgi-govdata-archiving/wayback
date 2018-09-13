# Command Line Interface
# See scripts/ directory for associated executable(s). All of the interesting
# functionality is implemented in this module to make it easier to test.
from docopt import docopt
import pandas
from tqdm import tqdm
from web_monitoring import db
from web_monitoring import internetarchive as ia


# These functions lump together library code into monolithic operations for the
# CLI. They also print. To access this functionality programmatically, it is
# better to use the underlying library code.


def _add_and_monitor(versions):
    cli = db.Client.from_env()  # will raise if env vars not set
    # Wrap verions in a progress bar.
    versions = tqdm(versions, desc='importing', unit=' versions')
    print('Submitting Versions to web-monitoring-db...')
    import_ids = cli.add_versions(versions)
    print('Import jobs IDs: {}'.format(import_ids))
    print('Polling web-monitoring-db until import jobs are finished...')
    errors = cli.monitor_import_statuses(import_ids)
    if errors:
        print("Errors: {}".format(errors))


def import_ia(url, *, from_date=None, to_date=None, maintainers=None,
              tags=None, skip_unchanged='resolved-response'):
    skip_responses = skip_unchanged == 'response'
    with ia.WaybackClient() as wayback:
        # Pulling on this generator does the work.
        versions = (wayback.timestamped_uri_to_version(version.date,
                                                       version.raw_url,
                                                       url=version.url,
                                                       maintainers=maintainers,
                                                       tags=tags,
                                                       view_url=version.view_url)
                    for version in wayback.list_versions(url,
                                                         from_date=from_date,
                                                         to_date=to_date,
                                                         skip_repeats=skip_responses))

        if skip_unchanged == 'resolved-response':
            versions = _filter_unchanged_versions(versions)

        _add_and_monitor(versions)


def _filter_unchanged_versions(versions):
    """
    Take an iteratable of importable version dicts and yield only versions that
    differ from the previous version of the same page.
    """
    last_hashes = {}
    for version in versions:
        if last_hashes.get(version['page_url']) != version['version_hash']:
            last_hashes[version['page_url']] = version['version_hash']
            yield version


def _parse_date_argument(date_string):
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
wm import ia <url> [--from <from_date>] [--to <to_date>] [options]

Options:
-h --help                     Show this screen.
--version                     Show version.
--maintainers <maintainers>   Comma-separated list of entities that maintain
                              the imported pages.
--tags <tags>                 Comma-separated list of tags to apply to pages
--skip-unchanged <skip_type>  Skip consecutive captures of the same content.
                              Can be:
                                `none` (no skipping),
                                `response` (if the response is unchanged), or
                                `resolved-response` (if the final response
                                    after redirects is unchanged)
                              [default: resolved-response]
"""
    arguments = docopt(doc, version='0.0.1')
    if arguments['import']:
        skip_unchanged = arguments['--skip-unchanged']
        if skip_unchanged not in ('none', 'response', 'resolved-response'):
            print('--skip-unchanged must be one of `none`, `response`, '
                  'or `resolved-response`')
            return

        if arguments['ia']:
            import_ia(url=arguments['<url>'],
                      maintainers=arguments.get('--maintainers'),
                      tags=arguments.get('--tags'),
                      from_date=_parse_date_argument(arguments['<from_date>']),
                      to_date=_parse_date_argument(arguments['<to_date>']),
                      skip_unchanged=skip_unchanged)


if __name__ == '__main__':
    main()
