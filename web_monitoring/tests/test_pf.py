import pytest
import web_monitoring.pagefreezer as pf


url1 = 'http://web.archive.org/web/20151204035406/http://www.energy.gov:80/technologytransitions/us-department-energys-clean-energy-investment-center'
url2 = 'http://web.archive.org/web/20151229231229/http://energy.gov:80/technologytransitions/us-department-energys-clean-energy-investment-center'


@pytest.mark.skip(reason="PF diffs are no longer used and require PAGE_FREEZER_API_KEY environment var")
def test_compare_and_df():
    # basic test just to exercise the important functions
    res = pf.compare(url1, url2)
    assert res['status'] == 'ok'
    assert 'result' in res

    df = pf.result_into_df(res['result'])
    assert all(df.columns == ['new', 'offset', 'old', 'state'])
