import json
import os
import requests
import pandas as pd


COMPARE_ENDPOINT = "https://api1.pagefreezer.com/v1/api/utils/diff/compare"
STATE_LOOKUP = { -1: "Removal", 0: "Change", 1: "Addition" }


# mutable singleton for stashing API key and potentially other stuff
_settings = {}


def set_api_key(api_key):
    _settings['api_key'] = api_key


# At import time, grab API key from env if possible. User can always override.
if 'PAGE_FREEZER_API_KEY' in os.environ:
    set_api_key(os.environ['PAGE_FREEZER_API_KEY'])


def compare(url_1, url_2):
    """
    Query PageFreezer and result the raw response as JSON dict.

    Parameters
    ----------
    url_1: string
    url_2: string

    Returns
    -------
    response: dict
    """
    response = requests.post(COMPARE_ENDPOINT,
                             data=json.dumps({"url1": url_1, "url2": url_2}),
                             headers= {"Accept": "application/json",
                                       "Content-Type": "application/json",
                                       "x-api-key": _settings['api_key']})
    assert response.ok
    return response.json()


def result_into_df(result):
    """
    Load the data in a PageFreezer result into a pandas.DataFrame.

    result : dict
        the 'result' payload in a PageFreezer response

    Returns
    -------
    df : DataFrame

    Examples
    --------

    Query PageFreezer and pack the result into a DataFrame.
    >>> response = compare(url_1, url_2)
    >>> df = result_into_df(response['result'])
    """
    old=[]
    new=[]
    offset=[]
    state = []
    for diff in result['output']['diffs']:
        old.append(diff['old'])
        new.append(diff['new'])
        offset.append(diff['offset'])
        state.append(STATE_LOOKUP[diff['change']])
    df = pd.DataFrame({"old" : old, "new": new, "offset": offset,
                       "state": pd.Categorical(state)})
    return df


def display_pairs(result):
    from IPython.display import HTML, display
    pairs = [(diff['new'], diff['old']) for diff in result['output']['diffs']]
    for new, old in pairs:
        display(HTML('<hr /'))
        display(HTML(old))
        display(HTML(new))


class PageFreezer:

    state_lookup = STATE_LOOKUP

    def __init__(self,url_1, url_2, api_key = None):
        self.api_key = api_key
        self.url_1 = url_1
        self.url_2 = url_2
        self.run_query()
        self.parse_to_df()

    def report(self):
        print("Delta Score: ", self.query_result['delta_score'], " Number of changes: ",len(self.dataframe) )
        counts = self.dataframe.groupby('state').count()['old']
        counts.index = counts.index.to_series().map(self.state_lookup)
        print(counts)

    def run_query(self):
        self.query_result = compare(self.url1, self.url2)['result']

    def parse_to_df(self):
        self.dataframe = result_into_df(self.query_result)

    def full_html_changes(self):
        from IPython.display import display, HTML
        display(HTML(self.query_result['output']['html']))
        return self.query_result['output']['html']

    def to_csv(self, filename):
        self.dataframe.to_csv(filename)

    def diff_pairs(self):
        diff_pairs = [(elem['new'], elem['old']) for elem in self.query_result['output']['diffs']]
        from IPython.display import display, HTML
        for pair in diff_pairs:
            display(HTML(pair[1]))
