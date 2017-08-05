# Functions for interacting with web-monitoring-db
import json
import os
import requests


# mutable singleton for stashing web-monitoring-db url, potentially other stuff
settings = {}
# At import time, grab settings from env if possible. User can always override.
settings['db_url'] = os.environ.get('WEB_MONITORING_DB_URL')
settings['db_email'] = os.environ.get('WEB_MONITORING_DB_EMAIL')
settings['db_password'] = os.environ.get('WEB_MONITORING_DB_PASSWORD')

WEB_MONITORING_CREATE_IMPORT_API = '{db_url}/api/v0/imports'
WEB_MONITORING_SHOW_IMPORT_API = '{db_url}/api/v0/imports/{import_id}'


def post_versions(versions):
    """
    Submit versions for importing into web-monitoring-db.

    Parameters
    ----------
    versions : iterable
        iterable of dicts from :func:`format_version`
    """
    # Existing documentation of import API is in this PR:
    # https://github.com/edgi-govdata-archiving/web-monitoring-db/pull/32
    url = WEB_MONITORING_CREATE_IMPORT_API.format(db_url=settings['db_url'])
    return requests.post(url,
                         auth=(settings['db_email'], settings['db_password']),
                         headers={'Content-Type': 'application/x-json-stream'},
                         data='\n'.join(map(json.dumps, versions)))


def query_import_status(import_id):
    """
    Check on the status of a bulk import job.

    Parameters
    ----------
    import_id : integer
    """
    url = WEB_MONITORING_SHOW_IMPORT_API.format(db_url=settings['db_url'],
                                                import_id=import_id)
    return requests.get(url,
                        auth=(settings['db_email'], settings['db_password']))
