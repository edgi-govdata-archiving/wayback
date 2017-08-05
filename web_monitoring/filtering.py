from urllib.parse import urlparse
from bs4 import BeautifulSoup

day_list = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
month_list = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
tag_list = ['<td class="c" id="displayMonthEl"', '<td class="c" id="displayDayEl"', '<td class="c" id="displayYearEl"']
social_media = ['twitter.com', 'platform.twitter.com']


def df_filter(df):

    df['review'] = 'yes'
    df['id'] = 'none'
    df['priority'] = 1.0
    df['annotation'] = 'no annotation'

    for index,row in df.iterrows():
        if ((str(row['new']).lower() in month_list) and (str(row['old']).lower() in month_list)):
            df.loc[index] = df.loc[index].replace(df.loc[index]['review'], 'no')
            df.loc[index] = df.loc[index].replace(df.loc[index]['id'], 'Date/Time')
            df.loc[index] = df.loc[index].replace(df.loc[index]['priority'], 0.1)
            df.loc[index] = df.loc[index].replace(df.loc[index]['annotation'], 'Repeated Changes')

        for s in tag_list:
            if (((s in str(row['new'])) and (s in str(row['old'])))):
                df.loc[index] = df.loc[index].replace(df.loc[index]['review'], 'no')
                df.loc[index] = df.loc[index].replace(df.loc[index]['id'], 'Date/Time')
                df.loc[index] = df.loc[index].replace(df.loc[index]['priority'], 0.1)
                df.loc[index] = df.loc[index].replace(df.loc[index]['annotation'], 'Repeated Changes')
                break

        if (str(row['state']) == 'Change'):
            social_soup = BeautifulSoup(str(row['new']), 'lxml')
            social_list = list(social_soup.find_all(['a', 'script']))
            for x in social_list:
                if (x.name == 'a'):
                    if ('href' in x.attrs.keys()):
                        if (urlparse(x['href']).netloc in social_media):
                            df.loc[index] = df.loc[index].replace(df.loc[index]['review'], 'no')
                            df.loc[index] = df.loc[index].replace(df.loc[index]['id'], 'Social Media')
                            df.loc[index] = df.loc[index].replace(df.loc[index]['priority'], 0.1)
                            df.loc[index] = df.loc[index].replace(df.loc[index]['annotation'], 'Repeated Changes')
                        if (urlparse(x['href']).scheme == 'mailto'):
                            df.loc[index] = df.loc[index].replace(df.loc[index]['review'], 'no')
                            df.loc[index] = df.loc[index].replace(df.loc[index]['id'], 'Contact info')
                            df.loc[index] = df.loc[index].replace(df.loc[index]['priority'], 0.1)
                            df.loc[index] = df.loc[index].replace(df.loc[index]['annotation'], 'Repeated Changes')

            date_list = list(social_soup.find_all(['meta'], attrs={"http-equiv":"last-modified"}))
            for y in date_list:
                if (y['http-equiv'] == "last-modified"):
                    df.loc[index] = df.loc[index].replace(df.loc[index]['review'], 'no')
                    df.loc[index] = df.loc[index].replace(df.loc[index]['id'], 'Date/Time')
                    df.loc[index] = df.loc[index].replace(df.loc[index]['priority'], 0.1)
                    df.loc[index] = df.loc[index].replace(df.loc[index]['annotation'], 'Repeated Changes')

    return df
