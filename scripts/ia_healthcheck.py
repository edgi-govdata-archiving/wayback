from datetime import datetime, timedelta
import random
from ..web_monitoring import db
from ..web_monitoring import internetarchive


MAX_CAPTURE_AGE = timedelta(hours=72)
LINKS_TO_CHECK = 5


def query_webmondb():
    """
    Query the web monitoring SCANNER API to get random links from the database
    Interger -> List
    """
    try:
        response = db.Client.from_env()
    except Exception as e:
        print('Could not access Web Monitoring API')
        print(e)
        return []
    else:
        page = response.list_pages(chunk=1, chunk_size=1)
        url_count = page['meta']['total_results']
        return ([response.list_pages(chunk=number, chunk_size=1)
            ['data'][0]['url']
            for number in random.sample(range(url_count), LINKS_TO_CHECK)])


def query_waybackCDX(url):
    """
    Query Wayback Machine using CDX API
    Get a list of versions of a url, and check for ValueError.
    String -> JSON
    """
    try:
        verisons = internetarchive.list_versions (url, from_date=datetime.now()
            - MAX_CAPTURE_AGE)
        verision = next(verisons)
    except ValueError as e:
        print(e)
        status = False
        return status
    except:
        print("Could not access Wayback CDX API")
    else:
        status = True
        return status


def output_file(responses):
    """
    Write Output to a Text file
    List -> None
    """
    fileoutput = open("ia_healthcheck.txt", "w")
    healthy_links = 0
    unhealthy_links = 0

    if not responses:
        fileoutput.write('No links were returned.')
    else:
        for (url, status) in responses:
            fileoutput.write(str(status) + ': ' + str(url)+'\n\n\n')
            if status:
                healthy_links += 1
            else:
                unhealthy_links += 1
        fileoutput.write('Found: {} Healthy Links and {} Unhealthy Links.'
.format(healthy_links, unhealthy_links))
    fileoutput.close()
    return


def output_email():
    """
    Send Output to and Email
    List -> None
    """
    return

# Get the random list of links from the Web Monitoring DB
# Get the responses of the links from the Wayback URL
# Check to see if the responses are within the time limit and write the output


if __name__ == "__main__":

    links = query_webmondb()
    links = ['sdfs', 'http://epa.gov']
    responses = [(url, query_waybackCDX(url)) for url in links if url]
    output_file(responses)
