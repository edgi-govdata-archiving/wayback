===============
Release History
===============

v0.4.5 (2024-02-01)
-------------------

In v0.4.4, we broke *archived mementos* of rate limit errors — they started raising exceptions instead of returning the actual memento. We now correctly return mementos of rate limit errors while still raising exceptions for actual live rate limit errors from the Wayback Machine itself. (:issue:`158`)


v0.4.4 (2023-11-27)
-------------------

This release makes some small fixes to rate limits and retries in order to better match with the current behavior of Wayback Machine servers:

- Updated the :meth:`wayback.WaybackClient.search` rate limit to 1 call per second (it was previously 1.5 per second). (:issue:`140`)
- Delayed retries for 60 seconds when receiving rate limit errors from the server. (:issue:`142`)
- Added more logging around requests and rate limiting. This should make it easier to debug future rate limit issues. (:issue:`139`)
- Fixed calculation of the ``time`` attribute on :class:`wayback.exceptions.WaybackRetryError`. It turns out it was only accounting for the time spent waiting between retries and skipping the time waiting for the server to respond! (:issue:`142`)
- Fixed some spots where we leaked HTTP connections during retries or during exception handling. (:issue:`142`)

The next minor release (v0.5) will almost certainly include some bigger changes to how rate limits and retries are handled.


v0.4.3 (2023-09-26)
-------------------

This is mainly a compatibility release: it adds support for urllib3 v2.x and the next upcoming major release of Python, v3.12.0. It also adds support for multiple filters in :meth:`wayback.WaybackClient.search`. There are no breaking changes.


Features
^^^^^^^^

You can now apply multiple filters to a search by using a list or tuple for the ``filter_field`` parameter of :meth:`wayback.WaybackClient.search`. (:issue:`119`)

For example, to search for all captures at ``nasa.gov`` with a 404 status and “feature” somewhere in the URL:

.. code-block:: python

   client.search('nasa.gov/',
                 match_type='prefix',
                 filter_field=['statuscode:404',
                               'urlkey:.*feature.*'])


Fixes & Maintenance
^^^^^^^^^^^^^^^^^^^

- Add support for Python 3.12.0. (:issue:`123`)
- Add support for urllib3 v2.x (urllib3 v1.20+ also still works). (:issue:`116`)


v0.4.3a1 (2023-09-22)
---------------------

This is a test release for properly supporting the upcoming release of Python 3.12.0. Please file an issue if you encounter issues using on Python 3.12.0rc3 or later. (:issue:`123`)


v0.4.2 (2023-05-29)
-------------------

Wayback is not compatible with urllib3 v2, and this release updates the package's requirements to make sure Pip and other package managers install compatible versions of Wayback and urllib3. There are no other fixes or new features.


v0.4.1 (2023-03-07)
-------------------

Features
^^^^^^^^

:class:`wayback.Memento` now has a ``links`` property with information about other URLs that are related to the memento, such as the previous or next mementos in time. It’s a dict where the keys identify the relationship (e.g. ``'prev memento'``) and the values are dicts with additional information about the link. (:issue:`57`) For example::

  {
      'original': {
          'url': 'https://www.fws.gov/birds/',
          'rel': 'original'
      },
      'first memento': {
          'url': 'https://web.archive.org/web/20050323155300id_/http://www.fws.gov:80/birds',
          'rel': 'first memento',
          'datetime': 'Wed, 23 Mar 2005 15:53:00 GMT'
      },
      'prev memento': {
          'url': 'https://web.archive.org/web/20210125125216id_/https://www.fws.gov/birds/',
          'rel': 'prev memento',
          'datetime': 'Mon, 25 Jan 2021 12:52:16 GMT'
      },
      'next memento': {
          'url': 'https://web.archive.org/web/20210321180831id_/https://www.fws.gov/birds',
          'rel': 'next memento',
          'datetime': 'Sun, 21 Mar 2021 18:08:31 GMT'
      },
      'last memento': {
          'url': 'https://web.archive.org/web/20221006031005id_/https://fws.gov/birds',
          'rel': 'last memento',
          'datetime': 'Thu, 06 Oct 2022 03:10:05 GMT'
      }
  }

One use for these is to iterate through additional mementos. For example, to get the previous memento::

  client.get_memento(memento.links['prev memento']['url'])


Fixes & Maintenance
^^^^^^^^^^^^^^^^^^^

- Fix an issue where the :attr:`Memento.url` attribute might be slightly off from the exact URL that was captured (it could have a different protocol, different upper/lower-casing, etc.). (:issue:`99`)

- Fix an error when getting a memento for a redirect in ``view`` mode. If you called :meth:`wayback.WaybackClient.get_memento` with a URL that turned out to be a redirect at the given time and set the ``mode`` option to :attr:`wayback.Mode.view`, you’d get an exception saying “Memento at {url} could not be played.” Now this works just fine. (:issue:`109`)


v0.4.0 (2022-11-10)
-------------------

Breaking Changes
^^^^^^^^^^^^^^^^

This release includes a significant overhaul of parameters for :meth:`wayback.WaybackClient.search`.

- Removed parameters that did nothing, could break search, or that were for internal use only: ``gzip``, ``showResumeKey``, ``resumeKey``, ``page``, ``pageSize``, ``previous_result``.

- Removed support for extra, arbitrary keyword parameters that could be added to each request to the search API.

- All parameters now use snake_case. (Previously, parameters that were passed unchanged to the HTTP API used camelCase, while others used snake_case.) The old, non-snake-case names are deprecated, but still work. They’ll be completely removed in v0.5.0.

  - ``matchType`` → ``match_type``
  - ``fastLatest`` → ``fast_latest``
  - ``resolveRevisits`` → ``resolve_revisits``

- The ``limit`` parameter now has a default value. There are very few cases where you should not set a ``limit`` (not doing so will typically break pagination), and there is now a default value to help prevent mistakes. We’ve also added documentation to explain how and when to adjust this value, since it is pretty complex. (:issue:`65`)

- Expanded the method documentation to explain things in more depth and link to more external references.

While we were at it, we also renamed the ``datetime`` parameter of :meth:`wayback.WaybackClient.get_memento` to ``timestamp`` for consistency with :class:`wayback.CdxRecord` and :class:`wayback.Memento`. The old name still works for now, but it will be fully removed in v0.5.0.


Features
^^^^^^^^

- :attr:`wayback.Memento.headers` is now case-insensitive. The keys of the ``headers`` dict are returned with their original case when iterating, but lookups are performed case-insensitively. For example::

    list(memento.headers) == ['Content-Type', 'Date']
    memento.headers['Content-Type'] == memento.headers['content-type']

  (:issue:`98`)

- There are now built-in rate limits for calls to ``search()`` and ``get_memento()``. The default values should keep you from getting temporarily blocked by the Wayback Machine servers, but you can also adjust them when instantiating :class:`wayback.WaybackSession`:

  .. code-block:: python

     # Limit get_memento() calls to 2 per second (or one every 0.5 seconds):
     client = WaybackClient(WaybackSession(memento_calls_per_second=2))

     # These now take a minimum of 0.5 seconds, even if the Wayback Machine
     # responds instantly (there's no delay on the first call):
     client.get_memento('http://www.noaa.gov/', timestamp='20180816111911')
     client.get_memento('http://www.noaa.gov/', timestamp='20180829092926')

  A huge thanks to @LionSzl for implementing this. (:issue:`12`)


Fixes & Maintenance
^^^^^^^^^^^^^^^^^^^

- All API requests to archive.org now use HTTPS instead of HTTP. Thanks to @sundhaug92 for calling this out. (:issue:`81`)

- Headers from the original archived response are again included in :attr:`wayback.Memento.headers`. As part of this, the ``headers`` attribute is now case-insensitive (see new features above), since the Internet Archive servers now return headers with different cases depending on how the request was made. (:issue:`98`)


v0.3.3 (2022-09-30)
-------------------

This release extends the timestamp parsing fix from version 0.3.2 to handle a similar problem, but with the month portion of timestamps in addition to the day. It also implements a small performance improvement in timestamp parsing. Thanks to @edsu for discovering this issue and addressing this. (:issue:`88`)


v0.3.2 (2021-11-16)
-------------------

Some Wayback CDX records have invalid timestamps with ``"00"`` for the day-of-month portion. :meth:`wayback.WaybackClient.search` previously raised an exception when parsing CDX records with this issue, but now handles them safely. Thanks to @8W9aG for discovering this issue and addressing it. (:issue:`85`)


v0.3.1 (2021-10-14)
-------------------

Some Wayback CDX records have no ``length`` information, and previously caused :meth:`wayback.WaybackClient.search` to raise an exception. These records will have their ``length`` property set to ``None`` instead of a number. Thanks to @8W9aG for discovering this issue and addressing it. (:issue:`83`)


v0.3.0 (2021-03-19)
-------------------

This release marks a *major* update we’re really excited about: :meth:`wayback.WaybackClient.get_memento` no longer returns a ``Response`` object from the `Requests package <https://requests.readthedocs.io/>`_ that takes a lot of extra work to interpret correctly. Instead, it returns a new :class:`wayback.Memento` object. It’s really similar to the ``Response`` we used to return, but doesn’t mix up current and historical data — it represents the historical, archived HTTP response that is stored in the Wayback Machine. This is a big change to the API, so we’ve bumped the version number to ``0.3.x``.


Notable Changes
^^^^^^^^^^^^^^^

- **Breaking change:** :meth:`wayback.WaybackClient.get_memento` takes new parameters and has a new return type. More details below.

- **Breaking change:** :func:`wayback.memento_url_data` now returns 3 values instead of 2. The last value is a string representing the playback mode (see below description of the new ``mode`` parameter on :meth:`wayback.WaybackClient.get_memento` for more about playback modes).

- Requests to the Wayback Machine now have a default timeout of 60 seconds. This was important because we’ve seen many recent issues where the Wayback Machine servers don’t always close connections.

  If needed, you can disable this by explicitly setting ``timeout=None`` when creating a :class:`wayback.WaybackSession`. Please note this is *not* a timeout on how long a whole request takes, but on the time between bytes received.

- :meth:`wayback.WaybackClient.get_memento` now raises :class:`wayback.exceptions.NoMementoError` when the requested URL has never been archived by the WaybackMachine. It no longer raises ``requests.exceptions.HTTPError`` under any circumstances.

You may notice that removing APIs from the `Requests package <https://requests.readthedocs.io/>`_ is a theme here. Under the hood, *Wayback* still uses *Requests* for HTTP requests, but we expect to change that in order to ensure this package is thread-safe. We will bump the version to v0.4.x when doing so.


get_memento() Parameters
^^^^^^^^^^^^^^^^^^^^^^^^

The parameters in :meth:`wayback.WaybackClient.get_memento` have been re-organized. The method signature is now:

.. code-block:: python

   def get_memento(self,
                   url,                        # Accepts new types of values.
                   datetime=None,              # New parameter.
                   mode=Mode.original,         # New parameter.
                   *,                          # Everything below is keyword-only.
                   exact=True,
                   exact_redirects=None,
                   target_window=24 * 60 * 60,
                   follow_redirects=True)      # New parameter.

- All parameters except ``url`` (the first parameter) from v0.2.x must now be specified with keywords, and cannot be specified positionally.

  If you previously used keywords, your code will be fine and no changes are necessary:

  .. code-block:: python

     # This still works great!
     client.get_memento('http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/',
                        exact=False,
                        exact_redirects=False,
                        target_window=3600)

  However, positional parameters like the following will now cause problems, and you should switch to the above keyword form:

  .. code-block:: python

     # This will now cause you some trouble :(
     client.get_memento('http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/',
                        False,
                        False,
                        3600)

- The ``url`` parameter can now be a normal, non-Wayback URL or a :class:`wayback.CdxRecord`, and new ``datetime`` and ``mode`` parameters have been added.

  Previously, if you wanted to get a memento of what ``http://www.noaa.gov/`` looked like on August 1, 2018, you would have had to construct a complex string to pass to ``get_memento()``:

  .. code-block:: python

     client.get_memento('http://web.archive.org/web/20180801000000id_/http://www.noaa.gov/')

  Now you can pass the URL and time you want as separate parameters:

  .. code-block:: python

     client.get_memento('http://www.noaa.gov/', datetime.datetime(2018, 8, 1))

  If the ``datetime`` parameter does not specify a timezone, it will be treated as UTC (*not* local time).

  You can also pass a :class:`wayback.CdxRecord` that you received from :meth:`wayback.WaybackClient.search` instead of a URL and time:

  .. code-block:: python

     for record in client.search('http://www.noaa.gov/'):
         client.get_memento(record)

  Finally, you can now specify the *playback mode* of a memento using the ``mode`` parameter:

  .. code-block:: python

     client.get_memento('http://www.noaa.gov/',
                        datetime=datetime.datetime(2018, 8, 1),
                        mode=wayback.Mode.view)

  The default mode is :attr:`wayback.Mode.original`, which returns the exact HTTP response body as was originally archived. Other modes reformat the response body so it’s more friendly for browsing by changing the URLs of links, images, etc. and by adding informational content to the page about the memento you are viewing. They are the modes typically used when you view the Wayback Machine in a web browser.

  Don’t worry, though — complete Wayback URLs are still supported. This code still works fine:

  .. code-block:: python

     client.get_memento('http://web.archive.org/web/20180801000000id_/http://www.noaa.gov/')

- A new ``follow_redirects`` parameter specifies whether to follow *historical* redirects (i.e. redirects that happened when the requested memento was captured). It defaults to ``True``, which matches the old behavior of this method.


get_memento() Returns a Memento Object
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``get_memento()`` no longer returns a response object from the `Requests package <https://requests.readthedocs.io/>`_. Instead it returns a specialized :class:`wayback.Memento` object, which is similar, but provides more useful information about the Memento than just the HTTP response from Wayback. For example, ``memento.url`` is the original URL the memento is a capture of (e.g. ``http://www.noaa.gov/``) rather than the Wayback URL (e.g. ``http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/``). You can still get the full Wayback URL from ``memento.memento_url``.

You can check out the full API documentation for :class:`wayback.Memento`, but here’s a quick guide to what’s available:

.. code-block:: python

   memento = client.get_memento('http://www.noaa.gov/home',
                                datetime(2018, 8, 16, 11, 19, 11),
                                exact=False)

   # These values were previously not available except by parsing
   # `memento.url`. The old `memento.url` is now `memento.memento_url`.
   memento.url == 'http://www.noaa.gov/'
   memento.timestamp == datetime(2018, 8, 29, 8, 8, 49, tzinfo=timezone.utc)
   memento.mode == 'id_'

   # Used to be `memento.url`:
   memento.memento_url == 'http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/'

   # Used to be a list of `Response` objects, now a *tuple* of Mementos. It
   # lists only the redirects that are actual Mementos and not part of
   # Wayback's internal machinery:
   memento.history == (Memento<url='http://noaa.gov/home'>,)

   # Used to be a list of `Response` objects, now a *tuple* of URL strings:
   memento.debug_history == ('http://web.archive.org/web/20180816111911id_/http://noaa.gov/home',
                             'http://web.archive.org/web/20180829092926id_/http://noaa.gov/home',
                             'http://web.archive.org/web/20180829092926id_/http://noaa.gov/')

   # Headers now only lists headers from the original archived response, not
   # additional headers from the Wayback Machine itself. (If there's
   # important information you needed in the headers, file an issue and let
   # us know! We'd like to surface that kind of information as attributes on
   # the Memento now.
   memento.headers = {'header_name': 'header_value',
                      'another_header': 'another_value',
                      'and': 'so on'}

   # Same as before:
   memento.status_code
   memento.ok
   memento.is_redirect
   memento.encoding
   memento.content
   memento.text


v0.2.6 (2021-03-18)
-------------------

Fix a major bug where a session’s ``timeout`` would not actually be applied to most requests. HUGE thanks to @LionSzl for discovering this issue and addressing it. (:issue:`68`)


v0.3.0 Beta 1 (2021-03-15)
--------------------------

:meth:`wayback.WaybackClient.get_memento` now raises :class:`wayback.exceptions.NoMementoError` when the requested URL has never been archived. It also now raises :class:`wayback.exceptions.MementoPlaybackError` in all other cases where an error was returned by the Wayback Machine (so you should never see a ``requests.exceptions.HTTPError``). However, you may still see other *network-level* errors (e.g. ``ConnectionError``).


v0.3.0 Alpha 3 (2020-11-05)
---------------------------

Fixes a bug in the new :class:`wayback.Memento` type where header parsing would fail for mementos with schemeless ``Location`` headers. (:issue:`61`)


v0.3.0 Alpha 2 (2020-11-04)
---------------------------

Fixes a bug in the new :class:`wayback.Memento` type where header parsing would fail for mementos with path-based ``Location`` headers. (:issue:`60`)


v0.3.0 Alpha 1 (2020-10-20)
---------------------------

**Breaking Changes:**

This release focuses on :meth:`wayback.WaybackClient.get_memento` and makes major, breaking changes to its parameters and return type. They’re all improvements, though, we promise!

**get_memento() Parameters**

The parameters in :meth:`wayback.WaybackClient.get_memento` have been re-organized. The method signature is now:

.. code-block:: python

   def get_memento(self,
                   url,                        # Accepts new types of values.
                   datetime=None,              # New parameter.
                   mode=Mode.original,         # New parameter.
                   *,                          # Everything below is keyword-only.
                   exact=True,
                   exact_redirects=None,
                   target_window=24 * 60 * 60,
                   follow_redirects=True)      # New parameter.

- All parameters except ``url`` (the first parameter) from v0.2.x must now be specified with keywords, and cannot be specified positionally.

  If you previously used keywords, your code will be fine and no changes are necessary:

  .. code-block:: python

     # This still works great!
     client.get_memento('http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/',
                        exact=False,
                        exact_redirects=False,
                        target_window=3600)

  However, positional parameters like the following will now cause problems, and you should switch to the above keyword form:

  .. code-block:: python

     # This will now cause you some trouble :(
     client.get_memento('http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/',
                        False,
                        False,
                        3600)

- The ``url`` parameter can now be a normal, non-Wayback URL or a :class:`wayback.CdxRecord`, and new ``datetime`` and ``mode`` parameters have been added.

  Previously, if you wanted to get a memento of what ``http://www.noaa.gov/`` looked like on August 1, 2018, you would have had to construct a complex string to pass to ``get_memento()``:

  .. code-block:: python

     client.get_memento('http://web.archive.org/web/20180801000000id_/http://www.noaa.gov/')

  Now you can pass the URL and time you want as separate parameters:

  .. code-block:: python

     client.get_memento('http://www.noaa.gov/', datetime.datetime(2018, 8, 1))

  If the ``datetime`` parameter does not specify a timezone, it will be treated as UTC (*not* local time).

  You can also pass a :class:`wayback.CdxRecord` that you received from :meth:`wayback.WaybackClient.search` instead of a URL and time:

  .. code-block:: python

     for record in client.search('http://www.noaa.gov/'):
         client.get_memento(record)

  Finally, you can now specify the *playback mode* of a memento using the ``mode`` parameter:

  .. code-block:: python

     client.get_memento('http://www.noaa.gov/',
                        datetime=datetime.datetime(2018, 8, 1),
                        mode=wayback.Mode.view)

  The default mode is :attr:`wayback.Mode.original`, which returns the exact HTTP response body as was originally archived. Other modes reformat the response body so it’s more friendly for browsing by changing the URLs of links, images, etc. and by adding informational content to the page about the memento you are viewing. They are the modes typically used when you view the Wayback Machine in a web browser.

  Don’t worry, though — complete Wayback URLs are still supported. This code still works fine:

  .. code-block:: python

     client.get_memento('http://web.archive.org/web/20180801000000id_/http://www.noaa.gov/')

- A new ``follow_redirects`` parameter specifies whether to follow *historical* redirects (i.e. redirects that happened when the requested memento was captured). It defaults to ``True``, which matches the old behavior of this method.


**get_memento() Returns a Memento Object**

``get_memento()`` no longer returns a response object from the `Requests package <https://requests.readthedocs.io/>`_. Instead it returns a specialized :class:`wayback.Memento` object, which is similar, but provides more useful information about the Memento than just the HTTP response from Wayback. For example, ``memento.url`` is the original URL the memento is a capture of (e.g. ``http://www.noaa.gov/``) rather than the Wayback URL (e.g. ``http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/``). You can still get the full Wayback URL from ``memento.memento_url``.

You can check out the full API docs for :class:`wayback.Memento`, but here’s a quick guide to what’s available:

.. code-block:: python

   memento = client.get_memento('http://www.noaa.gov/home',
                                datetime(2018, 8, 16, 11, 19, 11),
                                exact=False)

   # These values were previously not available except by parsing
   # `memento.url`. The old `memento.url` is now `memento.memento_url`.
   memento.url == 'http://www.noaa.gov/'
   memento.timestamp == datetime(2018, 8, 29, 8, 8, 49, tzinfo=timezone.utc)
   memento.mode == 'id_'

   # Used to be `memento.url`:
   memento.memento_url == 'http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/'

   # Used to be a list of `Response` objects, now a *tuple* of Mementos. It
   # Still lists only the redirects that are actual Mementos and not part of
   # Wayback's internal machinery:
   memento.history == (Memento<url='http://noaa.gov/home'>,)

   # Used to be a list of `Response` objects, now a *tuple* of URL strings:
   memento.debug_history == ('http://web.archive.org/web/20180816111911id_/http://noaa.gov/home',
                             'http://web.archive.org/web/20180829092926id_/http://noaa.gov/home',
                             'http://web.archive.org/web/20180829092926id_/http://noaa.gov/')

   # Headers now only lists headers from the original, archived response, not
   # additional headers from the Wayback Machine itself. (If there's
   # important information you needed in the headers, file an issue and let
   # us know! We'd like to surface that kind of information as attributes on
   # the Memento now.
   memento.headers = {'header_name': 'header_value',
                      'another_header': 'another_value',
                      'and': 'so on'}

   # Same as before:
   memento.status_code
   memento.ok
   memento.is_redirect
   memento.encoding
   memento.content
   memento.text

Under the hood, *Wayback* still uses `Requests <https://requests.readthedocs.io/>`_ for HTTP requests, but we expect to change that soon to ensure this package is thread-safe.


**Other Breaking Changes**

Finally, :func:`wayback.memento_url_data` now returns 3 values instead of 2. The last value is a string representing the playback mode (see above description of the new ``mode`` parameter on :meth:`wayback.WaybackClient.get_memento` for more about playback modes).


v0.2.5 (2020-10-19)
-------------------

This release fixes a bug where the ``target_window`` parameter for :meth:`wayback.WaybackClient.get_memento` did not work correctly if the memento you were redirected to was off by more than a day from the requested time. See :issue:`53` for more.


v0.2.4 (2020-09-07)
-------------------

This release is focused on improved error handling.

**Breaking Changes:**

- The timestamps in ``CdxRecord`` objects returned by :meth:`wayback.WaybackClient.search` now include timezone information. (They are always in the UTC timezone.)

**Updates:**

- The ``history`` attribute of a memento now only includes redirects that were mementos (i.e. redirects that would have been seen when browsing the recorded site at the time it was recorded). Other redirects involved in working with the memento API are still available in ``debug_history``, which includes all redirects, whether or not they were mementos.

- Wayback’s CDX search API sometimes returns repeated, identical results. These are now filtered out, so repeat search results will not be yielded from :meth:`wayback.WaybackClient.search`.

- :class:`wayback.exceptions.RateLimitError` will now be raised as an exception any time you breach the Wayback Machine's rate limits. This would previously have been :class:`wayback.exceptions.WaybackException`, :class:`wayback.exceptions.MementoPlaybackError`, or regular HTTP responses, depending on the method you called. It has a ``retry_after`` property that indicates how many seconds you should wait before trying again (if the server sent that information, otherwise it will be ``None``).

- :class:`wayback.exceptions.BlockedSiteError` will now be raised any time you search for a URL or request a memento that has been blocked from access (for example, in situations where the Internet Archive has received a takedown notice).


v0.2.3 (2020-03-25)
-------------------

This release downgrades the minimum Python version to 3.6! You can now use
Wayback in places like Google Colab.

The ``from_date`` and ``to_date`` arguments for
:meth:`wayback.WaybackClient.search` can now be ``datetime.date`` instances
in addition to ``datetime.datetime``.

Huge thanks to @edsu for implementing both of these!

v0.2.2 (2020-02-13)
-------------------

When errors were raised or redirects were involved in
``WaybackClient.get_memento()``, it was previously possible for connections to
be left hanging open. Wayback now works harder to make sure connections aren't
left open.

This release also updates the default user agent string to include the repo
URL. It now looks like:
``wayback/0.2.2 (+https://github.com/edgi-govdata-archiving/wayback)``

v0.2.1 (2019-12-01)
-------------------

All custom exceptions raised publicly and used internally are now exposed via
a new module, :mod:`wayback.exceptions`.

v0.2.0 (2019-11-26)
-------------------

Initial release of this project. See v0.1 below for information about a
separate project with the same name that has since been removed from PyPI.

v0.1
----

This version number is reserved because it was the last published release of a
separate Python project also named ``wayback`` that has since been deleted from
the Python Package Index and subsequently superseded by this one. That project,
which focused on the Wayback Machine's timemap API, was maintained by Jeff
Goettsch (username ``jgoettsch`` on the Python Package Index). Its source code
is still available on BitBucket at https://bitbucket.org/jgoettsch/py-wayback/.
