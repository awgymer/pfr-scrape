import ctypes
import multiprocessing as mp
import re
import string
import time
import requests
import pandas as pd
from pandas.api.types import is_string_dtype
import numpy as np
from pyquery import PyQuery as pq

from . import decorators

# time between requests, in seconds
THROTTLE_DELAY = 0.5

# variables used to throttle requests across processes
THROTTLE_LOCK = mp.Lock()
LAST_REQUEST_TIME = mp.Value(ctypes.c_longdouble,
                             time.time() - 2 * THROTTLE_DELAY)

@decorators.cache_html
def get_html(url, allow_redirect=False):
    """Gets the HTML for the given URL using a GET request.
    :url: the absolute URL of the desired page.
    :returns: a string of HTML.
    """
    with THROTTLE_LOCK:
        # sleep until THROTTLE_DELAY secs have passed since last request
        wait_left = THROTTLE_DELAY - (time.time() - LAST_REQUEST_TIME.value)
        if wait_left > 0:
            time.sleep(wait_left)

        # make request
        response = requests.get(url)

        # update last request time for throttling
        LAST_REQUEST_TIME.value = time.time()

    # raise ValueError on 4xx status code, get rid of comments, and return
    ret_code_limit = 400 if allow_redirect else 300
    if response.status_code >= ret_code_limit:
        raise ValueError(
            'Status Code {} received fetching URL "{}"'
            .format(response.status_code, url)
        )
    if response.url != url and not allow_redirect:
        raise ValueError(
            'Redirected from {} to {}'.format(url, response.url)
        )
    html = response.text
    html = html.replace('<!--', '').replace('-->', '')

    return html


def parse_table(table, flatten=True, footer=False, partial=False):
    """Parses a table from sports-reference sites into a pandas dataframe.
    :param table: the PyQuery object representing the HTML table
    :param flatten: if True, flattens relative URLs to IDs. otherwise, leaves
        all fields as text without cleaning.
    :param footer: If True, returns the summary/footer of the page. Recommended
        to use this with flatten=False. Defaults to False.
    :returns: pd.DataFrame
    """
    if not len(table):
        return pd.DataFrame()

    # get columns
    columns = [c.attrib['data-stat']
               for c in table('thead tr:not([class]) th[data-stat]')]

    # get data
    rows = list(table('tbody tr' if not footer else 'tfoot tr')
                .not_('.thead, .stat_total, .stat_average').items())
    # and td.attr['data-stat']=='team'
    data = [
        [flatten_links(td) if flatten else (td.text() if td.text() else None)
         for td in row.items('th,td')]
        for row in rows
    ]

    # make DataFrame
    df = pd.DataFrame(data, columns=columns, dtype='float')

    # add has_class columns
    allClasses = set(
        cls
        for row in rows
        if row.attr['class']
        for cls in row.attr['class'].split()
    )
    for cls in allClasses:
        df['has_class_' + cls] = [
            bool(row.attr['class'] and
                 cls in row.attr['class'].split())
            for row in rows
        ]

    # cleaning the DataFrame

    df.drop(['ranker', 'Xxx', 'Yyy', 'Zzz'],
            axis=1, inplace=True, errors='ignore')

    # year_id -> year (as int)
    if 'year_id' in df.columns:
        df.rename(columns={'year_id': 'year'}, inplace=True)
        if flatten:
            if is_string_dtype(df.year):
                df.year = df.year.str.translate(
                    str.maketrans({c: None for c in string.printable[10:]})
                ).replace('', np.nan)
            df.year = df.year.fillna(method='ffill')
            df['year'] = df.year.map(lambda s: str(s)[:4]).astype(int)

    if 'year' in df.columns:
        if is_string_dtype(df.year):
                df.year = df.year.str.translate(
                    str.maketrans({c: None for c in string.printable[10:]})
                ).replace('', np.nan)
        df.year = df.year.fillna(method='ffill')
        df['year'] = df.year.map(lambda s: str(s)[:4]).astype(int)

    # pos -> position
    if 'pos' in df.columns:
        df.rename(columns={'pos': 'position'}, inplace=True)

    # boxscore_word, game_date -> boxscore_id and separate into Y, M, D columns
    for bs_id_col in ('boxscore_word', 'game_date', 'box_score_text'):
        if bs_id_col in df.columns:
            df.rename(columns={bs_id_col: 'boxscore_id'}, inplace=True)
            break

    # ignore *, +, and other characters used to note things
    #df.replace(re.compile(r'[\*\+\u2605]', re.U), '', inplace=True)
    for col in df.columns:
        if hasattr(df[col], 'str'):
            df[col] = df[col].str.strip()

    if 'gs' in df.columns:
        if df['gs'].dtype not in [np.float64, np.int64]:
            df['gs'] = (df['gs'].str == '*')

    if 'game_num' in df.columns:
        df['game_num'] = df['game_num'].astype(int)

    if 'game_result' in df.columns:
        if flatten:
            df.rename(columns={'game_result': 'game_id'}, inplace=True)
            df[['game_result', 'team_score', 'opp_score']] = parse_table(
                table, flatten=False)[['game_result', 'team_score', 'opp_score']]
        else:
            df['game_result'], score_col = df.game_result.str.split(' ', 1).str
            df['team_score'], df['opp_score'] = score_col.str.split('-', 1).str
            df['team_score'] = df['team_score'].astype(int)
            df['opp_score'] = df['opp_score'].astype(int)

    if 'score' in df.columns:
        o_score, d_score = zip(*df.score.apply(lambda s: s.split('-')))
        df['team_score'] = o_score
        df['opp_score'] = d_score

    # player -> player_id and/or player_name
    if 'player' in df.columns:
        # remove HOF notation if present
        df['player'], hof_col, _ = df.player.str.partition(' HOF', expand=False).str
        if any(hof_col != ''):
            df['hof'] = hof_col
        if flatten:
            df.rename(columns={'player': 'player_id'}, inplace=True)
            # when flattening, keep a column for names
            player_names = parse_table(table, flatten=False)['player_name']
            df['player_name'] = player_names
        else:
            df.rename(columns={'player': 'player_name'}, inplace=True)

    # Keep an unexpanded copy of the description
    if 'description' in df.columns:
        if flatten:
            # when flattening, keep a column for names
            raw_descriptions = parse_table(table, flatten=False)['description']
            df['desc_raw'] = raw_descriptions
        else:
            df.rename(columns={'description': 'description'}, inplace=True)

    # team, team_name -> team_id
    for team_col in ('team', 'team_name'):
        if team_col in df.columns:
            # first, get rid of faulty rows
            df = df.loc[~df[team_col].isin(['XXX'])]
            if flatten:
                df.rename(columns={team_col: 'team_id'}, inplace=True)
                team_names = parse_table(table, flatten=False)[team_col]
                df[team_col] = team_names

    # season -> int
    if 'season' in df.columns and flatten:
        df['season'] = df['season'].astype(int)

    # handle date_game columns (different types)
    if 'date_game' in df.columns and flatten:
        date_re = r'month=(?P<month>\d+)&day=(?P<day>\d+)&year=(?P<year>\d+)'
        date_df = df['date_game'].str.extract(date_re, expand=True)
        if date_df.notnull().all(axis=1).any():
            df = pd.concat((df, date_df), axis=1)
        else:
            df.rename(columns={'date_game': 'boxscore_id'}, inplace=True)

    # game_location -> is_home
    if 'game_location' in df.columns and flatten:
        loc_dict = {'@':'A', None:'H', 'N':'N'}
        df['game_location'] = df['game_location'].map(loc_dict)
        #df.rename(columns={'game_location': 'is_home'}, inplace=True)

    # mp: (min:sec) -> float(min + sec / 60), notes -> NaN, new column
    if 'mp' in df.columns and df.dtypes['mp'] == object and flatten:
        mp_df = df['mp'].str.extract(
            r'(?P<m>\d+):(?P<s>\d+)', expand=True).astype(float)
        no_match = mp_df.isnull().all(axis=1)
        if no_match.any():
            df.loc[no_match, 'note'] = df.loc[no_match, 'mp']
        df['mp'] = mp_df['m'] + mp_df['s'] / 60

    # Split draft info column
    if 'draft_info' in df.columns:
        (df['draft_tm'], df['draft_rnd'],
         df['draft_pk'], df['draft_yr']) = df.draft_info.str.split(' / ').str

    # ignore *, +, and other characters used to note things
    df.replace(re.compile(r'[\*\+\u2605]', re.U), '', inplace=True)
    for col in df.columns:
        if hasattr(df[col], 'str'):
            df[col] = df[col].str.strip()

    # converts number-y things to floats
    def convert_to_float(val):
        # percentages: (number%) -> float(number * 0.01)
        m = re.search(r'([-\.\d]+)\%',
                      val if isinstance(val, str) else str(val), re.U)
        try:
            if m:
                return float(m.group(1)) / 100 if m else val
            if m:
                return int(m.group(1)) + int(m.group(2)) / 60
        except ValueError:
            return val
        # salaries: $ABC,DEF,GHI -> float(ABCDEFGHI)
        m = re.search(r'\$[\d,]+',
                      val if isinstance(val, str) else str(val), re.U)
        try:
            if m:
                return float(re.sub(r'\$|,', '', val))
        except Exception:
            return val
        # generally try to coerce to float, unless it's an int or bool
        try:
            if isinstance(val, (int, bool)):
                return val
            else:
                return float(val)
        except Exception:
            return val

    if flatten:
        df = df.applymap(convert_to_float)
        # Convert numeric cols empty vals to NaN
        for c in ['pass_adj_yds_per_att', 'pass_cmp_perc', 'pass_rating', 'pass_yds_per_att',
                  'rec_yds_per_rec', 'rec_yds_per_tgt', 'rush_yds_per_att']:
            try:
                df[c].replace('', np.nan, inplace=True)
            except KeyError:
                pass

    df = df.loc[df.astype(bool).any(axis=1)]

    if 'has_class_partial_table' in df and not partial:
        df['has_class_partial_table'] = df['has_class_partial_table']==True
        df.loc[~df['has_class_partial_table']]

    return df


def parse_info_table(table):
    """Parses an info table, like the "Game Info" table or the "Officials"
    table on the PFR Boxscore page. Keys are lower case and have spaces/special
    characters converted to underscores.

    :table: PyQuery object representing the HTML table.
    :returns: A dictionary representing the information.
    """
    ret = {}
    for tr in list(table('tr').not_('.thead').items()):
        th, td = list(tr('th, td').items())
        key = th.text().lower()
        key = re.sub(r'\W', '_', key)
        val = flatten_links(td)
        ret[key] = val
    return ret


def parse_officials_table(table):
    """Parses the "Officials"
    table on the PFR Boxscore page. Keys are lower case and have spaces/special
    characters converted to underscores.

    :table: PyQuery object representing the HTML table.
    :returns: A dictionary representing the information.
    """
    ret = {}
    for tr in list(table('tr').not_('.thead').items()):
        th, td = list(tr('th, td').items())
        key = th.text().lower()
        key = re.sub(r'\W', '_', key)
        val = flatten_links(td)
        ret[key] = (val, td.text())
    return ret


def parse_awards_table(table):
    """Parses an awards table, like the "Pro Bowls" table on a PFR player page.

    :table: PyQuery object representing the HTML table.
    :returns: A list of the entries in the table, with flattened links.
    """
    return [flatten_links(tr) for tr in list(table('tr').items())]


def flatten_links(td, _recurse=False):
    """Flattens relative URLs within text of a table cell to IDs and returns
    the result.
    :td: the PyQuery object for the HTML to convert
    :returns: the string with the links flattened to IDs
    """

    # helper function to flatten individual strings/links
    def _flatten_node(c, strip_s):
        if isinstance(c, str):
            return c.strip() if strip_s else c
        elif 'href' in c.attrib:
            c_id = rel_url_to_id(c.attrib['href'])
            c_alt = c.text_content().strip() if strip_s else c.text_content()
            return c_id if c_id else c_alt
        else:
            return flatten_links(pq(c), _recurse=True)

    # if there's no text, just return None
    if td is None or not td.text():
        return '' if _recurse else None

    # don't strip if the contents are a list - causes problems with regexes
    strip_s = len(td.contents()) < 2
    return ''.join(_flatten_node(c, strip_s) for c in td.contents())


@decorators.memoize
def rel_url_to_id(url):
    """Converts a relative URL to a unique ID.
    Here, 'ID' refers generally to the unique ID for a given 'type' that a
    given datum has. For example, 'BradTo00' is Tom Brady's player ID - this
    corresponds to his relative URL, '/players/B/BradTo00.htm'. Similarly,
    '201409070dal' refers to the boxscore of the SF @ DAL game on 09/07/14.
    Supported types:
    * player/...
    * boxscores/...
    * teams/...
    * years/...
    * leagues/...
    * awards/...
    * coaches/...
    * officials/...
    * schools/...
    * schools/high_schools.cgi?id=...
    :returns: ID associated with the given relative URL.
    """
    year_regex = r'.*/years/(\d{4}).*|.*/gamelog/(\d{4}).*'
    player_regex = r'.*/players/(?:\w/)?(.+?)(?:/|\.html?)'
    boxscores_regex = r'.*/boxscores/(.+?)\.html?'
    team_regex = r'.*/teams/(\w{3})/.*'
    coach_regex = r'.*/coaches/(.+?)\.html?'
    stadium_regex = r'.*/stadiums/(.+?)\.html?'
    ref_regex = r'.*/officials/(.+?r)\.html?'
    college_regex = r'.*/schools/(\S+?)/.*|.*college=([^&]+)'
    hs_regex = r'.*/schools/high_schools\.cgi\?id=([^\&]{8})'
    bs_date_regex = r'.*/boxscores/index\.f?cgi\?(month=\d+&day=\d+&year=\d+)'
    league_regex = r'.*/leagues/(.*_\d{4}).*'
    award_regex = r'.*/awards/(.+)\.htm'

    regexes = [
        year_regex,
        player_regex,
        boxscores_regex,
        team_regex,
        coach_regex,
        stadium_regex,
        ref_regex,
        college_regex,
        hs_regex,
        bs_date_regex,
        league_regex,
        award_regex,
    ]

    for regex in regexes:
        match = re.match(regex, url, re.I)
        if match:
            return [_f for _f in match.groups() if _f][0]

    # things we don't want to match but don't want to print a WARNING
    if any(
            url.startswith(s) for s in
            (
                '/play-index/',
            )
    ):
        return url

    print('WARNING. NO MATCH WAS FOUND FOR "{}"'.format(url))
    return url
