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
WEB_MONITORING_GET_CHANGES_API = '{db_url}/api/v0/pages/{page_id}/changes/{from_version}..{to_version}'
WEB_MONITORING_POST_CHANGES_API ='{db_url}/api/v0/pages/{page_id}/changes/{from_version}..{to_version}/annotations'
WEB_MONITORING_GET_VERSION_API = '{db_url}/api/v0/pages/{page_id}/versions/{version_id}'

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

def get_version_source_url(page_id, version_id):
    """
    Get the source url of a version.

    Parameters
    ----------
    page_id* : string
    version_id* : string

    * -> required fields
    """
    url = WEB_MONITORING_GET_VERSION_API.format(db_url=settings['db_url'],
                                                page_id=page_id,
                                                version_id=version_id)
    response = requests.get(url,
                            auth=(settings['db_email'], settings['db_password']))
    result = response1.json()
    source_url = result1['data']['source_metadata']['url']
    return source_url

def get_changes(page_id, from_version_id, to_version_id):
    """
    Get the changes between two versions.

    Parameters
    ----------
    page_id* : string
    from_version_id : string
    to_version_id* : string

    * -> required fields
    if from_version_id is not given, it will be treated as version immediately
    prior to to_version
    """
    url = WEB_MONITORING_GET_CHANGES_API.format(db_url=settings['db_url'],
                                                page_id=page_id,
                                                from_version=from_version_id,
                                                to_version=to_version_id)
    return requests.get(url,
                        auth=(settings['db_email'], settings['db_password']))

def post_changes(page_id, from_version_id, to_version_id, annotations):
    """
    Submit updated annotations for a change between versions.

    Parameters
    ----------
    page_id* : string
    from_version_id : string
    to_version_id* : string
    annotations* : Dictionary object
    """

    url = WEB_MONITORING_POST_CHANGES_API.format(db_url=settings['db_url'],
                                                 page_id=page_id,
                                                 from_version=from_version_id,
                                                 to_version=to_version_id,
                                                 annotations=json.dumps(annotations))
    return requests.post(url,
                         auth=(settings['db_email'], settings['db_password']),
                         headers={'Content-Type': 'application/x-json-stream'})



    











