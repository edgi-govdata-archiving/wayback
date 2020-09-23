===============================
wayback
===============================

.. image:: https://circleci.com/gh/edgi-govdata-archiving/wayback/tree/main.svg?style=shield
        :target: https://circleci.com/gh/edgi-govdata-archiving/wayback
        :alt: Build Status

.. image:: https://img.shields.io/pypi/v/wayback.svg
        :target: https://pypi.python.org/pypi/wayback
        :alt: Download Latest Version from PyPI

.. image:: https://img.shields.io/badge/%E2%9D%A4-code%20of%20conduct-blue.svg?style=flat
        :target: https://github.com/edgi-govdata-archiving/overview/blob/main/CONDUCT.md
        :alt: Code of Conduct

.. image:: https://readthedocs.org/projects/wayback/badge/?version=stable
        :target: https://wayback.readthedocs.io/en/stable/?badge=stable
        :alt: Documentation Status


*Wayback* is A Python API to the `Internet Archive’s Wayback Machine <https://web.archive.org/>`_. It gives you tools to search for and load mementos (historical copies of web pages).

The Internet Archive maintains an official `“internetarchive” <https://archive.org/services/docs/api/internetarchive/>`_ Python package, but it does not focus on the Wayback Machine. Instead, it is mainly concerned with the APIs and tools that manage the Internet Archive as a whole: managing items and collections. These are how e-books, audio recordings, movies, and other content in the Internet Archive are managed. It doesn’t, however, provide particularly good tools for finding or loading historical captures of specific URLs (i.e. the part of the Internet Archive called the “Wayback Machine”). That’s what this package does.

* Documentation:
    * Current Release: https://wayback.readthedocs.io/en/stable/
    * Development: https://wayback.readthedocs.io/en/latest/


Installation & Basic Usage
--------------------------

Install via pip on the command line::

    $ pip install wayback

Then, in a Python script, import it and create a client:

.. code-block:: python

    import wayback
    client = wayback.WaybackClient()

Finally, search for all the mementos of ``nasa.gov`` before 1999 and download them:

.. code-block:: python

    for record in client.search('http://nasa.gov', to_date=date(1999, 1, 1)):
        memento = client.get_memento(record)

Read the `full documentation <https://wayback.readthedocs.io/>`_ for a more in-depth tutorial and complete API reference documentation at https://wayback.readthedocs.io/


Code of Conduct
---------------

This repository falls under EDGI’s `Code of Conduct <https://github.com/edgi-govdata-archiving/overview/blob/main/CONDUCT.md>`_. Pleas take a moment to review it before commenting on or creating issues and pull requests.


Contributors
------------

Thanks to the following people for their contributions and help on this package! See our `contributing guidelines <https://github.com/edgi-govdata-archiving/wayback/blob/main/CONTRIBUTING.rst>`_ to find out how you can help.

- `Dan Allan <https://github.com/danielballan>`_ (Code, Tests, Documentation, Reviews)
- `Rob Brackett <https://github.com/Mr0grog>`_ (Code, Tests, Documentation, Reviews)
- `Ed Summers <https://github.com/edsu>`_ (Code, Tests)


License & Copyright
-------------------

Copyright (C) 2019-2020 Environmental Data and Governance Initiative (EDGI)

This program is free software: you can redistribute it and/or modify it under the terms of the 3-Clause BSD License. See the `LICENSE <https://github.com/edgi-govdata-archiving/wayback/blob/master/LICENSE>`_ file for details.
