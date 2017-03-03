# Archive layout & xml formal

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
