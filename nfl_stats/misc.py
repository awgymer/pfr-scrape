from pyquery import PyQuery as pq
import pandas as pd

from . import utils


PENS_BASE = 'http://www.nflpenalties.com'
FMB_BASE = 'https://www.teamrankings.com/nfl/player-stat'


def get_penalty_logs(weeks=None, years=None):
    log_temp = PENS_BASE + '/week.php?week={}&year={}&view=log'
    all_dfs = []
    for y in years:
        print('Getting penalties for {}'.format(y))
        for w in weeks:
            print('Week {}'.format(w))
            log_url = log_temp.format(w, y)
            try:
                doc = pq(utils.get_html(log_url))
            except ValueError as err:
                print(err)
                print('Page not available for {} week {}'.format(y, w))
                continue
            table = '<table>' + doc('table').html() + '</table>'
            df = parse_pens_table(table)
            df['year'] = y
            df['week'] = w
            df['game_no'] = [
                tuple(sorted([x.week, x.year, x.Against, x.Beneficiary], key=str))
                for _, x in df.iterrows()
            ]
            df['game_no'] = df['game_no'].factorize()[0]
            all_dfs.append(df)
    return pd.concat(all_dfs) if all_dfs else None


def get_fumbles_lost(years=None):
    fmbl_temp = FMB_BASE + '/fumbles-lost?season_id={}'
    all_dfs = []
    for y in years:
        print('Getting fumbles for {}'.format(y))
        y_id = y - 2002
        fmb_url = fmbl_temp.format(y_id)
        try:
            doc = pq(utils.get_html(fmb_url))
        except ValueError as err:
            print(err)
            print('Page not available for {}'.format(y))
            continue
        table = '<table>' + doc('table').html() + '</table>'
        df = parse_fumbles_lost_table(table)
        df['year'] = y
        all_dfs.append(df)
    return pd.concat(all_dfs) if all_dfs else None


def parse_pens_table(table, footer=False):
    if not len(table):
        return pd.DataFrame()

    df = pd.read_html(table, parse_dates=['Date'])[0]

    if not footer:
        df = df[df.Penalty != 'Totals']
    return df


def parse_fumbles_lost_table(table):
    if not len(table):
        return pd.DataFrame()

    df = pd.read_html(table)[0]
    return df

