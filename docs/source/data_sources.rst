*****************************************
Overview of Sources of Archived Web Pages
*****************************************

The EDGI Website Monitoring project currently ingests data from three sources:

* Internet Archive Wayback Machine
* Versionista (legacy)

Internet Archive
================

The Internet Archive Wayback Machine stores snapshots of HTML pages. The
Internet Archive at large stores a broader range of archived content, but we
are focused on the Wayback Machine.


The original response from the Internet Archive is a list of 'mementos' (or
'versions', as we call them). Each line contains information about a version. At
times, a line may be a 'TimeMap', which is essentially a link to the next list
of mementos.


`source_metadata` : Byte sequences containing information separated by semi-colons of each version stored in Internet Archive.
We extract the useful information i.e. the date and uri from each memento.

Example:

.. code-block:: python

    b'<http://web.archive.org/web/19970711094601/http://www.nasa.gov:80/>; rel="memento"; datetime="Fri, 11 Jul 1997 09:46:01 GMT",'

`Reference on Mementos & TimeMaps <http://mementoweb.org/guide/quick-intro/>`_

Versionista
===========

Versionista returns a JSON blob which contains the following fields:

* `account` : The Versionista account we're logging into to get the versions. We have two accounts - `versionista1` & `versionista2`
* `siteName` : The website of the file.
* `agency` : The name of the Government agency which owns the website.
* `versionistaSiteUrl` : A link to a website as it is stored on Versionista.
* `versionistaPageUrl` : A link to a webpage as it is stored on Versionista.
* `pageUrl` : The page's true URL.
* `pageTitle` : The title of the page as defined in the `title` tag.
* `siteId` : Id of the website in Versionista.
* `pageId` : Id of a webpage in Versionista.
* `versionId` : Id of a version in Versionista.
* `url` : The full URL to view this version in Versionista. You’ll need to be logged into the appropriate Versionista account to make use of it.
* `date` : The date and time when the version was captured.
* `hasContent` : Indicates if Versionista has stored any content of the page or not. There is a limit on the size of the versions Versionista can store. `True` or `False`
* `diffWithPreviousUrl` : URL to diff view in Versionista (comparing with previous version).
* `diffWithPreviousDate` : The capture date of the first ever captured version of the page.
* `diffWithFirstUrl` : URL to diff view in Versionista (comparing with first version).
* `diffWithFirstDate` : The capture date of the current version of the page.
* `textDiff` : A dictionary with the URL to the text diff view in Versionista and its SHA 256 hash and length.
* `diff`: A dictionary with the URL to the entire diff view in Verisionista and its SHA 256 hash and length.
* `filePath` : Path to the diff file which is stored in our archive.
*  `hash` : The diff file's SHA 256 hash.

`Recent Versionista output file <https://s3-us-west-2.amazonaws.com/edgi-versionista-archive/versionista1/metadata-2017-06-20T00%3A00Z.json>`_

======================================= ================ ===========
Aspect                                  Internet Archive Versionista
======================================= ================ ===========
Type                                    Byte Sequence    JSON
Version/file can be directly accessed   No               No
Elapsed time details                    Not present      Not Present
Page meta tag data/ header              Not present      Not Present
======================================= ================ ===========
