===============
Release History
===============

v0.3.0 Beta 1 (2021-03-15)
--------------------------

:meth:`wayback.WaybackClient.get_memento` now raises :class:`wayback.exceptions.NoMementoError` when the requeted URL has never been archived. It also now raises :class:`wayback.exceptions.MementoPlaybackError` in all other cases where an error was returned by the Wayback Machine (so you should never see a ``requests.exceptions.HTTPError``). However, you may still see other *network-level* errors (e.g. ``ConnectionError``).


v0.3.0 Alpha 3 (2020-11-05)
---------------------------

Fixes a bug in the new :class:`wayback.Memento` type where header parsing would fail for mementos with schemeless ``Location`` headers. (`#61 <https://github.com/edgi-govdata-archiving/wayback/pull/61>`_)


v0.3.0 Alpha 2 (2020-11-04)
---------------------------

Fixes a bug in the new :class:`wayback.Memento` type where header parsing would fail for mementos with path-based ``Location`` headers. (`#60 <https://github.com/edgi-govdata-archiving/wayback/pull/60>`_)


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

This release fixes a bug where the ``target_window`` parameter for :meth:`wayback.WaybackClient.get_memento` did not work correctly if the memento you were redirected to was off by more than a day from the requested time. See `#53 <https://github.com/edgi-govdata-archiving/wayback/pull/53>`_ for more.


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
