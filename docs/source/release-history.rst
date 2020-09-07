===============
Release History
===============

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
