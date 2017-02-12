# page-freezer-cli
CLI tools &amp; data management protocols for interacting with Page Freezer.

See [the versionista outputter repo](https://github.com/edgi-govdata-archiving/versionista-outputter) and the [version tracking ui](https://github.com/edgi-govdata-archiving/version-tracking-ui) repos for earlier work that has some overlap/similar goals. 

## Motivation
We are currently receiving moderate-sized archives of government web pages (10 ^2 Gb/week) from our partners at [PageFreezer](http://pagefreezer.com). In principle, these archives are a gold mine of information -- but we need tools to analyze them. Those tools need to be able to execute a diff operation against large numbers of pages, and to filter out the vast bulk of changes in order to identify the important ones.

## Getting Involved
We need your help! Please read through the rest of this document and see what you can help with!  We have not yet settled on a language for our work, though we imagine python and ruby are the most likely candidates. 

## Specifications

In order to be useful, tools will need to be able to do the following:

1. read archive directories and identify comparison candidates for a given URL
2. perform diffs on large numbers of pages (a useful scale for our work is the "subdomain" -- a full or partial government domain that we have identified as relevant to environment/climate change).
3. [filter those diffs](#filters-are-essential) to eliminate irrelevant, trivial, or repetitive changes
4. output results in a form that is immediately acessible/helpful to an analyst. One likely format is a CSV file containing at least the following information:
   - page title
   - page url
   - comparison dates
   - **link to user-friendly diff** -- this can be local or served over http

## What we know so far

### Archive layout & xml formal
Any scripts we write to automate monitoring will need to know something about the archives we are receiving from PageFreezer. 

Each Page Freezer archive for a domain BASEURL consists of a zipfile with the following structure:

- Base URL is `storage/export/climate/BASEURL_NUMERICALID_YYYY-MM-DD/http[s]_URL/`
- inside this you'll find a file: `http[s]_URL_MM_DD_YYYY.xml`
- and a directory: `MM_DD_YYYY/`
  - potentially containing multiple subdirs of the form: `http[s]_URL`, where URL is either the BASEURL or an external domain cantaining resources linked from BASEURL pages.

A [short example PageFreezer xml is provided in this repo](archives/http_www.climateandsatellites.org_01_20_2017.xml). It shows three kinds of elements: `<site>`, `<snapshot>` and `<document>`, of which the last three are probably the most important.  Here's one such: 
```xml
 <document url="http://www.climateandsatellites.org/SpryAssets/SpryCollapsiblePanel.css" timestamp="20-01-2017 06:22 PM" hash="324832c39c58c0412a98e0aac9e00d5ea20ded8d1ce1e78ebeb5137984d3ca7a1f11ef89dcad4792b0818196d53756e547eefa135099f3443be1f6a782426353" filename="http_www.climateandsatellites.org/SpryAssets/SpryCollapsiblePanel.css"/>
```

### PageFreezer API

The PageFreezer `compare` method takes the following parameters: 

| Parameter	| Description |
|-----------|-------------|
| `source` (optional)|	Default: `url`. <br>`url`=url1 and url2 must be URL of the target document. <br>`text`=url1 and url2 contains HTML text document itself. |
| `url1` |	The source URL or HTML |
| `url2` |	The target URL or HTML |
| `diffmode` | (optional)	Default: `0`. <br>`0`=No pre-processing, <br>`1`=extra white spaces removed, <br>`2`=[\s]* are removed,<br>`3`=HTML tags are removed for full-text comparison |
| `html`  (optional) |	Default: `1`. <br>`2`=HTML with HEAD, <br>`1`=HTML without HEAD, <br>`0`=False (no HTML output). |
| `snippet`  (optional)	 | Default: `200` (characters). It will generate snippets of changes. |

See [our PageFreezer Api page](./pagefreezer-api.md) for more details.

### HTML Diff tools exist

Both Python and Ruby have excellent DOM-aware HTML diff libraries. See the discussion in [this issue from the versionista-outputter repo](https://github.com/edgi-govdata-archiving/versionista-outputter/issues/1) for some Ruby hints. 

### Filters are essential

The vast majority of web page changes are of limited interest to us, and so we need to write filters that allow us to prioritize changes. Our analysts are currently drowning in false positives. Here are some examples:

* A substantial percentage of pages on [climate.nasa.gov](http://climate.nasa.gov) include a `Latest Resources` box on the right-hand side of the main page. Every page that contains this box will be marked as a "changed page" by our version tracking software. The relevant change can be seen on `line 1305` of [this diff](https://gist.github.com/va-client/c25c6def28b760f25e3190b1e986d2e3/revisions#diff-8a777b7cd35d6141f393542135beb397R1306). A simple ad-hoc filter that discards changes from `<aside class='list_view_module'>` would cut out about [30%*](# "Made Up Number.") of our positives from `climate.nasa.gov`.
* Many domains update their "Last Updated" date at random. Again, cutting these out would help.
* Many pages contain user-invisible changes which, for now at least, are not interesting to us

[The archives directory of this repo](./archives) contains a number of examples. Filenames starting with `falsepos-` are paradigmatic cases for filter design. Filenames starting with `truepos` are examples of changes we actually care about. Obviously filters will need to be tested against real datasets at some point. We hope to make those available soon.

Current materials:
* [versionista-outputter](https://github.com/edgi-govdata-archiving/versionista-outputter)
