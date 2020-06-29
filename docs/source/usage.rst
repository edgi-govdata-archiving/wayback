*****
Usage
*****

Search for historical mementos (archived copies) of a URL. Download metadata
about the mementos and/or the memento content itself.

Tutorial
========

What is the earliest memento of nasa.gov?
-----------------------------------------

Instantiate a :class:`WaybackClient`.

.. ipython:: python

   from wayback import WaybackClient
   client = WaybackClient()

Search for all Wayback's records for nasa.gov.

.. ipython:: python

   results = client.search('nasa.gov')

This statement should execute fairly quickly because it doesn't actually do
much work. The object we get back, ``results``, is a *generator*, a "lazy"
object from which we can pull results, one at a time. As we pull items
out of it, it loads them as needed from the Wayback Machine in chronological
order. We can see that ``results`` by itself is not informative:

.. ipython:: python

   results

There are couple ways to pull items out of generator like ``results``. One
simple way is to use the built-in Python function :func:`next`, like so:

.. ipython:: python

   record = next(results)

This takes a moment to run because, now that we've asked to see the first item
in the generator, this lazy object goes to fetch a chunk of results from the
Wayback Machine. Looking at the record in detail,

.. ipython:: python

   record

we can find our answer: Wayback's first memento of nasa.gov was in 1996. We
can use dot access on ``record`` to access the timestamp specifically.

.. ipython:: python

   record.timestamp

How many times does the word 'mars' appear on nasa.gov?
-------------------------------------------------------

Above, we access the metadata for the oldest memento on nasa.gov, stored in
the variable ``record``. Starting from where we left off, we'll access the
*content* of the memento and do a very simple analysis.

The Wayback Machine provides two ways to look at the data it has captured.
There is a copy edited for human viewers on the web, available at the record's
``view_url``, and there is the original copy of what was captured when the page
was originally scraped, availabe at the record's ``raw_url``. For analysis
purposes, we generally want the ``raw_url``.

Let's download the raw content using ``WaybackClient``. (You could download the
content directly with an HTTP library like ``requests``, but ``WaybackClient``
adds extra tools for dealing with Wayback Machine servers.)

.. ipython:: python

   response = client.get_memento(record.raw_url)
   content = response.content.decode()

We can use the built-in method ``count`` on strings to count the number of
times that ``'mars'`` appears in the content.

.. ipython:: python

   content.count('mars')

This is case-sensitive, so to be more accurate we should convert the content to
lowercase first.

.. ipython:: python

   content.lower().count('mars')

We picked up a couple additional occurrences that the original count missed.

API Documentation
=================

The Wayback Machine exposes its data through two different mechanisms,
implementing two different standards for archival data, the CDX API and the
Memento API. We implement a Python client that can speak both.

.. autoclass:: wayback.WaybackClient

    .. automethod:: search
    .. automethod:: get_memento

.. autoclass:: wayback.CdxRecord

.. autoclass:: wayback.WaybackSession

    .. automethod:: reset

Utility Functions
-----------------

.. autofunction:: wayback.memento_url_data

Exception Classes
-----------------

.. autoclass:: wayback.exceptions.WaybackException

.. autoclass:: wayback.exceptions.UnexpectedResponseFormat

.. autoclass:: wayback.exceptions.BlockedByRobotsError

.. autoclass:: wayback.exceptions.BlockedSiteError

.. autoclass:: wayback.exceptions.MementoPlaybackError

.. autoclass:: wayback.exceptions.RateLimitError

.. autoclass:: wayback.exceptions.WaybackRetryError

.. autoclass:: wayback.exceptions.SessionClosedError
