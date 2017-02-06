mport requests
import json
import pandas as pd

class PageFreezer:

    state_lookup = { -1: "Removal", 0: "Change", 1: "Addition" }

    def __init__(self,url_1, url_2, api_key = None):
        self.api_key = api_key
        self.url_1 = url_1
        self.url_2 = url_2
        self.run_query()
        self.parse_to_df()
        self.report()

    def report(self):
        print("Delta Score: ", self.query_result['delta_score'], " Number of changes: ",len(self.dataframe) )
        counts = self.dataframe.groupby('state').count()['old']
        counts.index = counts.index.to_series().map(self.state_lookup)
        print(counts)

    def run_query(self):
        result = requests.post( "https://api1.pagefreezer.com/v1/api/utils/diff/compare",
                  data=json.dumps({"url1":self.url_1, "url2":self.url_2}) ,
                  headers= { "Accept": "application/json", "Content-Type": "application/json", "x-api-key": self.api_key})
        self.query_result = result.json()['result']

    def parse_to_df(self):
        old=[]
        new=[]
        offset=[]
        state = []
        for diff in self.query_result['output']['diffs']:
            old.append(diff['old'])
            new.append(diff['new'])
            offset.append(diff['offset'])
            state.append(diff['change'])
        self.dataframe = pd.DataFrame({"old" : old, "new": new, "offset": offset, "state": state})

    def full_html_changes(self):
        from IPython.display import display, HTML
        display(HTML(a['output']['html']))
        return a['output']['html']

    def to_csv(self, filename):
        self.dataframe.to_csv(filename)

    def diff_pairs(self):
        diff_pairs = [(elem['new'], elem['old']) for elem in self.query_result['output']['diffs']]
        from IPython.display import display, HTML
        for pair in diff_pairs:
            display(HTML(pair[1]))

