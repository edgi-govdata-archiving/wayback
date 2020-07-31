===================================================================================================================
We’ve moved development of this repo to the ``main`` branch. You will not be able to merge changes into ``master``.
===================================================================================================================

**UPDATING LOCAL CLONES**

(via [this link](https://www.hanselman.com/blog/EasilyRenameYourGitDefaultBranchFromMasterToMain.aspx), thanks!)

If you have a local clone, you can update and change your default branch with the steps below.

.. code-block:: bash
  git checkout master
  git branch -m master main
  git fetch
  git branch --unset-upstream
  git branch -u origin/main
  git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main

The above steps accomplish:

1. Go to the master branch
2. Rename master to main locally
3. Get the latest commits from the server
4. Remove the link to origin/master
5. Add a link to origin/main
6. Update the default branch to be origin/main


===============================
wayback
===============================

.. image:: https://img.shields.io/travis/edgi-govdata-archiving/wayback.svg
        :target: https://travis-ci.org/edgi-govdata-archiving/wayback

.. image:: https://img.shields.io/pypi/v/wayback.svg
        :target: https://pypi.python.org/pypi/wayback


Python API to Internet Archive Wayback Machine

* Free software: 3-clause BSD license
* Documentation:
    * Current Release: https://wayback.readthedocs.io/en/stable/
    * Development: https://wayback.readthedocs.io/en/latest/


Features
--------

* TODO


Contributors
------------

Thanks to the following people for their contributions and help on this package! See our `contributing guidelines <https://github.com/edgi-govdata-archiving/wayback/blob/master/CONTRIBUTING.rst>`_ to find out how you can help.

- `Dan Allan <https://github.com/danielballan>`_ (Code, Tests, Documentation, Reviews)
- `Rob Brackett <https://github.com/Mr0grog>`_ (Code, Tests, Documentation, Reviews)
- `Ed Summers <https://github.com/edsu>`_ (Code, Tests)


License & Copyright
-------------------

Copyright (C) 2019-2020 Environmental Data and Governance Initiative (EDGI)

This program is free software: you can redistribute it and/or modify it under the terms of the 3-Clause BSD License. See the `LICENSE <https://github.com/edgi-govdata-archiving/wayback/blob/master/LICENSE>`_ file for details.
