# PageFreezer Python Module 

Quick and dirty module for accessing Page Freezer api. Convenience methods for getting changes in pandas dataframe, seeing HTML diffs etc.

## Usage

```python
import PageFreezer

pf = PageFreezer(url_old, url_new, api_key='') #api_key is the PageFreezer API key to be taken from Developers/Owners 
#without the API key value set, one gets "Key Error"
df = pf.dataframe #create a dataframe from PageFreezer object
df.to_csv('results.csv', encoding='utf-8') #set to utf-8 encoding and then convert the dataframe to csv
pf.full_html_changes()
pf.diff_pairs()
```

## Future stuff 

+ Add heuristics to be used as importance metric
+ Write out a html page that sumarizes the results 

