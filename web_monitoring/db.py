# Functions for interacting with web-monitoring-db
from dateutil.parser import parse as parse_timestamp
import functools
import json
import os
import requests
import tzlocal
import uuid as _uuid


# mutable singleton for stashing web-monitoring-db url, potentially other stuff
settings = {}
# At import time, grab settings from env if possible. User can always override.
settings['db_url'] = os.environ.get('WEB_MONITORING_DB_URL')
settings['db_email'] = os.environ.get('WEB_MONITORING_DB_EMAIL')
settings['db_password'] = os.environ.get('WEB_MONITORING_DB_PASSWORD')


def api_url():
    """Return api_url, using current db_url in settings."""
    db_url = settings['db_url']
    return f'{db_url}/api/v0'


def auth():
    """Return the current db_email, db_password from settings."""
    return (settings['db_email'], settings['db_password'])


def tzaware_iso_format(dt):
    """Express a datetime object in timezone-aware ISO format."""
    if dt.tzinfo is None:
        # This is naive. Assume they mean this time in the local timezone.
        dt_tzaware = dt.replace(tzinfo=tzlocal.get_localzone())
    return dt_tzaware.isoformat()

def time_range_string(start_date, end_date):
    """
    Parameters
    ----------
    start_date : datetime or None
    end_date : datetime or None

    Returns
    -------
    capture_time_query : None or string
        If None, do not query ``capture_time``.
    """
    if start_date is None and end_date is None:
        return None
    if start_date is not None:
        start_str = tzaware_iso_format(start_date)
    else:
        start_str = ''
    if end_date is not None:
        end_str = tzaware_iso_format(end_date)
    else:
        end_str = ''
    return f'{start_str}..{end_str}'


class MissingCredentials(RuntimeError):
    ...


def ensure_credentials(f):
    """Check that the module settings dict is populated."""
    @functools.wraps(f)
    def inner(*args, **kwargs):
        if None in settings.values():
            raise MissingCredentials("""
Before using the function, database credentials must be provided to the module.
You can do this in one of two ways:

1. Update the dictionary `web_monitoring.db.settings`.
2. Set the following environment variables and then reload the
   `web_monitoring.db` module.

   WEB_MONITORING_DB_URL
   WEB_MONITORING_DB_EMAIL
   WEB_MONITORING_DB_PASSWORD""")
        return f(*args, **kwargs)
    return inner


### PAGES ###


@ensure_credentials
def list_pages(chunk=None, chunk_size=None,
               site=None, agency=None, url=None, title=None,
               include_versions=None, include_latest=None,
               source_type=None, hash=None,
               start_date=None, end_date=None):
    """
    List all Pages, optionally filtered by search criteria.

    Parameters
    ----------
    chunk : integer, optional
        pagination parameter
    chunk_size : integer, optional
        number of items per chunk
    site : string, optional
    agency : string, optional
    url : string, optional
    title : string, optional
    include_versions : boolean, optional
    include_latest : boolean, optional
    source_type : string, optional
        such as 'versionista' or 'internetarchive'
    hash : string, optional
        SHA256 hash of Version content
    start_date : datetime, optional
    end_date : datetime, optional

    Returns
    -------
    response : dict
    """
    params = {'chunk': chunk,
              'chunk_size': chunk_size,
              'site': site,
              'agency': agency,
              'url': url,
              'title': title,
              'include_versions': include_versions,
              'source_type': source_type,
              'hash': hash,
              'capture_time': time_range_string(start_date, end_date)}
    url = f'{api_url()}/pages'
    res = requests.get(url, auth=auth(), params=params)
    res.raise_for_status()
    result = res.json()
    data = result['data']
    # In place, replace datetime strings with datetime objects.
    for page in data:
        page['created_at'] = parse_timestamp(page['created_at'])
        page['updated_at'] = parse_timestamp(page['updated_at'])
        if include_latest:
            page['latest']['capture_time'] = parse_timestamp(
                page['latest']['capture_time'])
        if include_versions:
            for v in page['versions']:
                v['created_at'] = parse_timestamp(v['created_at'])
                v['updated_at'] = parse_timestamp(v['updated_at'])
                v['capture_time'] = parse_timestamp(v['capture_time'])
    return result


@ensure_credentials
def get_page(page_id):
    """
    Lookup a specific Page by ID.

    Parameters
    ----------
    page_id : string

    Returns
    -------
    response : dict
    """
    url = f'{api_url()}/pages/{page_id}'
    res = requests.get(url, auth=auth())
    res.raise_for_status()
    result = res.json()
    # In place, replace datetime strings with datetime objects.
    data = result['data']
    data['created_at'] = parse_timestamp(data['created_at'])
    data['updated_at'] = parse_timestamp(data['updated_at'])
    for v in data['versions']:
        v['created_at'] = parse_timestamp(v['created_at'])
        v['updated_at'] = parse_timestamp(v['updated_at'])
        v['capture_time'] = parse_timestamp(v['capture_time'])
    return result


### VERSIONS ###


@ensure_credentials
def list_versions(page_id=None, chunk=None, chunk_size=None,
                  start_date=None, end_date=None,
                  source_type=None, hash=None,
                  source_metadata=None):
    """
    List Versions, optionally filtered by serach criteria, including Page.

    Parameters
    ----------
    page_id : string, optional
        restricts serach to Versions of a specific Page
    chunk : integer, optional
        pagination parameter
    chunk_size : integer, optional
        number of items per chunk
    start_date : datetime, optional
    end_date : datetime, optional
    source_type : string, optional
        such as 'versionista' or 'internetarchive'
    hash : string, optional
        SHA256 hash of Version content
    source_metadata : dict, optional
        Examples:

        * ``{'version_id': 12345678}``
        * ``{'account': 'versionista1', 'has_content': True}``

    Returns
    -------
    response : dict
    """
    params = {'chunk': chunk,
              'chunk_size': chunk_size,
              'capture_time': time_range_string(start_date, end_date),
              'source_type': source_type,
              'hash': hash}
    if source_metadata is not None:
        for k, v in source_metadata.items():
            params[f'source_metadata[{k}]'] = v
    if page_id is None:
        url = f'{api_url()}/versions'
    else:
        url = f'{api_url()}/pages/{page_id}/versions'
    res = requests.get(url, auth=auth(), params=params)
    res.raise_for_status()
    result = res.json()
    # In place, replace datetime strings with datetime objects.
    for v in result['data']:
        v['created_at'] = parse_timestamp(v['created_at'])
        v['updated_at'] = parse_timestamp(v['updated_at'])
        v['capture_time'] = parse_timestamp(v['capture_time'])
    return result


@ensure_credentials
def get_version(version_id):
    """
    Lookup a specific Version by ID.

    Parameters
    ----------
    version_id : string

    Returns
    -------
    response : dict
    """
    url = f'{api_url()}/versions/{version_id}'
    res = requests.get(url, auth=auth())
    res.raise_for_status()
    result = res.json()
    data = result['data']
    data['capture_time'] = parse_timestamp(data['capture_time'])
    data['updated_at'] = parse_timestamp(data['updated_at'])
    data['created_at'] = parse_timestamp(data['created_at'])
    return result


@ensure_credentials
def add_version(page_id, capture_time, uri, hash,
                 source_type, title, uuid=None, source_metadata=None):
    """
    Submit one new Version.

    See :func:`add_versions` for a more efficient bulk importer.

    Parameters
    ----------
    page_id : string
        Page to which the Version is associated
    uri : string
        URI of content (such as an S3 bucket or InternetArchive URL)
    hash : string
        SHA256 hash of Version content
    source_type : string
        such as 'versionista' or 'internetarchive'
    title : string
        content of ``<title>`` tag
    uuid : string, optional
        A new, unique Version ID (UUID4). If not specified, one will be
        generated.
    source_metadata : dict, optional
        free-form metadata blob provided by source

    Returns
    -------
    response : dict
    """
    # Do some type casting here as gentle error-checking.
    if uuid is None:
        uuid = _uuid.uuid4()
    version = {'uuid': str(uuid),
               'capture_time': capture_time.isoformat() + 'Z',
               'uri': str(uri),
               'hash': str(hash),
               'source_type': str(source_type),
               'title': str(title),
               'source_metadata': source_metadata}
    url = f'{api_url()}/pages/{page_id}/versions'
    res = requests.post(url, auth=auth(),
                        headers={'Content-Type': 'application/json'},
                        data=json.dumps(version))
    res.raise_for_status()
    return res.json()


@ensure_credentials
def add_versions(versions):
    """
    Submit versions in bulk for importing into web-monitoring-db.

    Parameters
    ----------
    versions : iterable
        iterable of dicts from :func:`format_version`

    Returns
    -------
    response : dict
    """
    # Existing documentation of import API is in this PR:
    # https://github.com/edgi-govdata-archiving/web-monitoring-db/pull/32
    url = f'{api_url()}/imports'
    res = requests.post(url, auth=auth(),
                        headers={'Content-Type': 'application/x-json-stream'},
                        data='\n'.join(map(json.dumps, versions)))
    res.raise_for_status()
    return res.json()


@ensure_credentials
def query_import_status(import_id):
    """
    Check on the status of a bulk import job.

    Parameters
    ----------
    import_id : integer

    Returns
    -------
    response : dict
    """
    url = f'{api_url()}/imports/{import_id}'
    res = requests.get(url, auth=auth())
    res.raise_for_status()
    return res.json()


### CHANGES AND ANNOTATIONS ###


@ensure_credentials
def list_changes(page_id):
    """
    List Changes between two Versions on a Page.

    Parameters
    ----------
    page_id : string

    Returns
    -------
    response : dict
    """
    url = f'{api_url()}/pages/{page_id}/changes/'
    res = requests.get(url, auth=auth())
    res.raise_for_status()
    result = res.json()
    # In place, replace datetime strings with datetime objects.
    for change in result['data']:
        change['created_at'] = parse_timestamp(change['created_at'])
        change['updated_at'] = parse_timestamp(change['updated_at'])
    return result


@ensure_credentials
def get_change(page_id, to_version_id, from_version_id=''):
    """
    Get a Changes between two Versions.

    Parameters
    ----------
    page_id : string
    to_version_id : string
    from_version_id : string, optional
        If from_version_id is not given, it will be treated as version
        immediately prior to ``to_version``.

    Returns
    -------
    response : dict
    """
    url = (f'{api_url()}/pages/{page_id}/changes/'
           f'{from_version_id}..{to_version_id}')
    res = requests.get(url, auth=auth())
    res.raise_for_status()
    result = res.json()
    # In place, replace datetime strings with datetime objects.
    data = result['data']
    data['created_at'] = parse_timestamp(data['created_at'])
    data['updated_at'] = parse_timestamp(data['updated_at'])
    return result


@ensure_credentials
def list_annotations(page_id, to_version_id, from_version_id=''):
    """
    List Annotations for a Change between two Versions.

    Parameters
    ----------
    page_id : string
    to_version_id : string
    from_version_id : string, optional
        If from_version_id is not given, it will be treated as version
        immediately prior to ``to_version``.

    Returns
    -------
    response : dict
    """
    url = (f'{api_url()}/pages/{page_id}/changes/'
           f'{from_version_id}..{to_version_id}/annotations')
    res = requests.get(url, auth=auth())
    res.raise_for_status()
    result = res.json()
    # In place, replace datetime strings with datetime objects.
    for a in result['data']:
        a['created_at'] = parse_timestamp(a['created_at'])
        a['updated_at'] = parse_timestamp(a['updated_at'])
    return result


@ensure_credentials
def add_annotation(annotation, page_id, to_version_id, from_version_id=''):
    """
    Submit updated annotations for a change between versions.

    Parameters
    ----------
    annotation : dict
    page_id : string
    to_version_id : string
    from_version_id : string, optional
        If from_version_id is not given, it will be treated as version
        immediately prior to ``to_version``.

    Returns
    -------
    response : dict
    """
    url = (f'{api_url()}/pages/{page_id}/changes/'
           f'{from_version_id}..{to_version_id}/annotations')
    res = requests.post(url, auth=auth(),
                        headers={'Content-Type': 'application/json'},
                        data=json.dumps(annotation))
    res.raise_for_status()
    return res.json()


@ensure_credentials
def get_annotation(annotation_id, page_id, to_version_id, from_version_id=''):
    """
    Get a specific Annontation.

    Parameters
    ----------
    annotation_id : string
    page_id : string
    to_version_id : string
    from_version_id : string, optional
        If from_version_id is not given, it will be treated as version
        immediately prior to ``to_version``.

    Returns
    -------
    response : dict
    """
    url = (f'{api_url()}/pages/{page_id}/changes/'
           f'{from_version_id}..{to_version_id}/annotations/{annotation_id}')
    res = requests.get(url, auth=auth())
    res.raise_for_status()
    result = res.json()
    # In place, replace datetime strings with datetime objects.
    data = result['data']
    data['created_at'] = parse_timestamp(data['created_at'])
    data['updated_at'] = parse_timestamp(data['updated_at'])
    return result


### CONVENIENCE FUNCTIONS ###


@ensure_credentials
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
    db_result = get_version(version_id)
    content_uri = db_result['data']['uri']
    res = requests.get(content_uri)
    res.raise_for_status()
    if res.headers.get('Content-Type', '').startswith('text/'):
        return res.text
    else:
        return res.content


def get_version_by_versionista_id(versionista_id):
    """
    Look up a Version by its Verisonista-issued ID.

    This is a convenience function for dealing with Versions ingested from
    Versionista.

    Parameters
    ----------
    versionista_id : string

    Returns
    -------
    response : dict
    """
    result = list_versions(source_type='versionista',
                           source_metadata={'version_id': versionista_id})
    # There should not be more than one match.
    data = result['data']
    if len(data) == 0:
        raise ValueError("No match found for versionista_id {}"
                         "".format(versionista_id))
    elif len(data) > 1:
        raise Exception("Multiple Versions match the versionista_id {}."
                        "Their web-monitoring-db version_ids are: {}"
                        "".format(versionista_id, [v['uuid'] for v in data]))
    # Hack 'data' to look like the result of get_version rather than the result
    # of list_versions.
    result['data'] = result['data'][0]
    return result


def get_version_uri(version_id, id_type='db', source_type='versionista', get_previous=False):
    """
    Get the uri of a version(snapshot) stored in the db.

    Parameters
    ----------
    version_id : string
    source_type : string, optional
        'versionista' by default
    get_previous : boolean
        False by default

    Returns
    -------
    source_uri or (source_uri, previous_id) depending on ``get_previous``
    """
    if (id_type == 'db'):
        result = get_version(version_id=version_id)
    elif (id_type == 'source'):
        result = get_version_by_versionista_id(versionista_id=version_id)
    else:
        raise ValueError('id type should be either "db" or "source"')
    # The functions above raise an exception if they don't get exactly one
    # result, so from here we can safely assume we have one result.
    source_uri = result['data']['uri']

    if (get_previous and source_type == 'versionista'):
        diff_with_previous_url = result['data']['source_metadata']['diff_with_previous_url']
        previous_id = diff_with_previous_url.split(':')[-1]
        return source_uri, previous_id
    else:
        return source_uri
