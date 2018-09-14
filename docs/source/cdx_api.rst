.. currentmodule:: web_monitoring.internetarchive

**********************************************
Python API to Internet Archive Wayback Machine
**********************************************

Search for historical snapshots of a URL. Download metadata about the snapshots
and/or the snapshot content itself.

We implement Python clients for the CDX and Memento APIs provided by Wayback
Machine.

Tutorial
========

TO DO

API Documentation
=================

.. autoclass:: WaybackClient

    .. automethod:: search
    .. automethod:: list_versions
    .. automethod:: timestamped_uri_to_version
