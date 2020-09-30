===============
Release History
===============

In Development
--------------

[Add information about changes in your PR here]

**Breaking Changes:**

- The parameters in :meth:`wayback.WaybackClient.get_memento` have been re-organized. All parameters from earlier versions must be specified with keywords instead of positionally, and two new parameters (``datetime`` and ``mode``) have been added.

  1. If you previously used keywords, your code will be fine and no changes are necessary:

     .. code-block:: python

        client.get_memento('http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/',
                           exact=False,
                           exact_redirects=False,
                           target_window=3600)

     However, positional parameters like the following will now cause problems, and you should switch to the above keyword form:

     .. code-block:: python

        client.get_memento('http://web.archive.org/web/20180816111911id_/http://www.noaa.gov/',
                           False,
                           False,
                           3600)

  2. The ``url`` parameter can now be a non-Wayback URL or a :class:`wayback.CdxRecord`, and new ``datetime`` and ``mode`` parameters have been added.

     Previously, if you wanted to get a memento of what ``http://www.noaa.gov/`` looked like on August 1, 2018, you would have had to construct a complex string to pass to ``get_memento()``:

     .. code-block:: python

        client.get_memento('http://web.archive.org/web/20180801000000id_/http://www.noaa.gov/')

     Now you can pass the URL and time you want as separate parameters:

     .. code-block:: python

        client.get_memento('http://www.noaa.gov/', datetime.datetime(2018, 8, 1))

        # The time can also be passed as the `datetime` keyword:
        client.get_memento('http://www.noaa.gov/', datetime=datetime.datetime(2018, 8, 1))

     If the ``datetime`` parameter does not specify a timezone, it will be interpreted as UTC (*not* local time).

     You can also pass a :class:`wayback.CdxRecord` that you received from :meth:`wayback.WaybackClient.search` instead of a URL and time:

     .. code-block:: python

        for record in client.search('http://www.noaa.gov/'):
            client.get_memento(record)

     Finally, you can now specify the *playback mode* of a memento using the ``mode`` parameter:

     .. code-block:: python

        client.get_memento('http://www.noaa.gov/',
                           datetime=datetime.datetime(2018, 8, 1),
                           mode=wayback.Mode.view)

     The default mode is :attr:`wayback.Mode.original`, which returns the exact HTTP response body as was originally archived. Other modes reformat the response body so it’s more friendly for browsing by changing the URLs or links, images, etc. and by adding informational content to the page (or other file type) about the memento you are viewing. They are the modes typically used when you view the Wayback Machine in a web browser.

     Don’t worry, though — complete Wayback URLs are still supported. This code still works fine:

     .. code-block:: python

        client.get_memento('http://web.archive.org/web/20180801000000id_/http://www.noaa.gov/')


**New Features:**

- :meth:`wayback.WaybackClient.get_memento` now takes a ``follow_redirects`` parameter. If false, *historical* redirects (i.e. redirects that happened when the requested memento was captured) are not followed. It defaults to ``True``, which is matches the old behavior of this method.


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
