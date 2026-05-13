============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every
little bit helps, and credit will always be given.

Before contributing, please be sure to take a look at our
`code of conduct <https://github.com/edgi-govdata-archiving/overview/blob/main/CONDUCT.md>`_.

You can contribute in many ways:

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/edgi-govdata-archiving/wayback/issues.

If you are reporting a bug, please include:

* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Fix Bugs
~~~~~~~~

Look through the GitHub issues for bugs. Anything tagged with "bug"
is open to whoever wants to implement it.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub issues for features. Anything tagged with "feature"
is open to whoever wants to implement it.

Write Documentation
~~~~~~~~~~~~~~~~~~~

wayback could always use more documentation, whether
as part of the official wayback docs, in docstrings,
or even on the web in blog posts, articles, and such.

Submit Feedback
~~~~~~~~~~~~~~~

The best way to send feedback is to file an issue at https://github.com/edgi-govdata-archiving/wayback/issues.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

Get Started!
------------

Ready to contribute? Here's how to set up `wayback` for local development.

1. Fork the `wayback` repo on GitHub.
2. Clone your fork locally::

    $ git clone git@github.com:your_username_here/wayback.git

3. Set up your local development environment::

    $ cd wayback/
    $ python -m venv .venv
    $ source .venv/bin/activate
    $ pip install -e ".[dev,docs]"
    $ pre-commit install

   .. note::
      The dev and docs dependencies are not compatible with each other on Python versions earlier than 3.10. In that case, you'll need separate virtualenvs for working on docs vs. code.

4. Create a branch for local development::

    $ git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

5. Make sure to pass CI checks before submitting your pull request. You can run the checks locally with::

    $ ruff check
    $ ruff format
    $ mypy
    $ pytest -v

6. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit -m "Your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature

7. Submit a pull request through the GitHub website.

Pull Request Guidelines
-----------------------

Before you submit a pull request, check that it meets these guidelines:

1. The pull request should include tests.
2. If the pull request adds functionality, the docs should be updated. Put
   your new functionality into a function with a docstring, and add the
   feature to the list in README.rst.
3. The pull request should work for Python 3.8 and for PyPy. After you submit your pull request, CircleCI will automatically run tests against all supported Python runtimes, so in most cases, you won't need to exhaustively test each of these yourself.
