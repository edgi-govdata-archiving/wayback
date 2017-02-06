# PageFreezer Python Module 

Quick and dirty module for accessing Page Freezer api. Convenience methods for getting changes in pandas dataframe, seeing HTML diffs etc.

## Usage

```python
import PageFreezer

pf = PageFreezer(url_old, url_new, api_key='')
pf.dataframe
pf.to_csv('results.csv')
pf.full_html_changes()
pf.diff_pairs()
```

## Future stuff 

+ Add heuristics to be used as importance metric
+ Write out a html page that sumarizes the results 

