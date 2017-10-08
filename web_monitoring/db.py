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


def auth():
    """Return db_email, db_password from settings."""
    return (settings['db_email'], settings['db_password'])


WEB_MONITORING_CREATE_IMPORT_API = '{db_url}/api/v0/imports'
WEB_MONITORING_SHOW_IMPORT_API = '{db_url}/api/v0/imports/{import_id}'
WEB_MONITORING_GET_CHANGES_API = '{db_url}/api/v0/pages/{page_id}/changes/{from_version}..{to_version}'
WEB_MONITORING_POST_CHANGES_API ='{db_url}/api/v0/pages/{page_id}/changes/{from_version}..{to_version}/annotations'
WEB_MONITORING_GET_VERSION_API = '{db_url}/api/v0/versions/{version_id}'
WEB_MONITORING_GET_VERSION_SOURCE_API = '{db_url}/api/v0/versions?source_type={source_type}&source_metadata[version_id]={version_id}'
WEB_MONITORING_SHOW_VERSION_API = '{db_url}/api/v0/versions/{version_id}'


def post_versions(versions):
    """
    Submit versions for importing into web-monitoring-db.

    Parameters
    ----------
    versions : iterable
        iterable of dicts from :func:`format_version`

    Returns
    -------
    response : :class:`requests.Response`
    """
    # Existing documentation of import API is in this PR:
    # https://github.com/edgi-govdata-archiving/web-monitoring-db/pull/32
    url = WEB_MONITORING_CREATE_IMPORT_API.format(db_url=settings['db_url'])
    return requests.post(url,
                         auth=auth(),
                         headers={'Content-Type': 'application/x-json-stream'},
                         data='\n'.join(map(json.dumps, versions)))


def query_import_status(import_id):
    """
    Check on the status of a bulk import job.

    Parameters
    ----------
    import_id : integer

    Returns
    -------
    response : :class:`requests.Response`
    """
    url = WEB_MONITORING_SHOW_IMPORT_API.format(db_url=settings['db_url'],
                                                import_id=import_id)
    return requests.get(url,
                        auth=auth())

def get_version_uri(version_id, id_type='db', source_type='versionista', get_previous=False):
    """
    Get the uri of a version(snapshot) stored in the db.

    Parameters
    ----------
    version_id* : string
    source_type : string
    get_previous : boolean
    * -> required fields
    """
    if (id_type == 'db'):
        url = WEB_MONITORING_GET_VERSION_API.format(db_url=settings['db_url'],
                                                    version_id=version_id)
    elif (id_type == 'source'):
        url = WEB_MONITORING_GET_VERSION_SOURCE_API.format(db_url=settings['db_url'],
                                                           source_type=source_type,
                                                           version_id=version_id)
    else:
        raise ValueError('Id type should be either "db" or "source"')

    response = requests.get(url,
                            auth=(settings['db_email'], settings['db_password']))
    result = response.json()

    if (len(result['data']) == 0):
        if(get_previous):
            return None, None
        else:
            return None

    source_uri = result['data'][0]['uri']

    if (get_previous and source_type == 'versionista'):
        diff_with_previous_url = result['data'][0]['source_metadata']['diff_with_previous_url']
        previous_id = diff_with_previous_url.split(':')[-1]
        return source_uri, previous_id
    else:
        return source_uri

def get_changes(page_id, to_version_id, from_version_id=''):
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
                        auth=auth())

def post_changes(page_id, to_version_id, annotations, from_version_id=''):
    """
    Submit updated annotations for a change between versions.

    Parameters
    ----------
    page_id* : string
    from_version_id : string
    to_version_id* : string
    annotations* : Dictionary object

    * -> required fields
    if from_version_id is not given, it will be treated as version immediately
    prior to to_version
    """

    url = WEB_MONITORING_POST_CHANGES_API.format(db_url=settings['db_url'],
                                                 page_id=page_id,
                                                 from_version=from_version_id,
                                                 to_version=to_version_id,
                                                 annotations=json.dumps(annotations))
    return requests.post(url,
                         auth=auth(),
                         headers={'Content-Type': 'application/x-json-stream'})


def fetch_version_content(version_id):
    """
    Download the saved content from a given Version.

    Parameters
    ----------
    version_id : string

    Returns
    -------
    content : bytes
    """

    url = WEB_MONITORING_SHOW_VERSION_API.format(db_url=settings['db_url'],
                                                 version_id=version_id)
    version = requests.get(url, auth=auth())
    content_uri = version.json()['data']['uri']
    return requests.get(content_uri).content
