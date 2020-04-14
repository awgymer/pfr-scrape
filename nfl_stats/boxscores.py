import re
import datetime
from functools import reduce

import numpy as np
import pandas as pd
from pyquery import PyQuery as pq

from nfl_stats import PFR_BASE
from . import decorators
from . import utils
from . import teams
from . import pbp


__all__ = ['BoxScore',]


GAMES_URL = PFR_BASE + '/years/{y}/games.htm'


def get_boxscore_ids(strt_yr, end_yr):
    all_bids = []
    for y in range(strt_yr, end_yr+1):
        game_url = GAMES_URL.format(y=y)
        doc = pq(utils.get_html(game_url))
        tab = utils.parse_table(doc('table#games'))
        bids = [b for b in list(tab['boxscore_id']) if b is not None]
        all_bids.extend(bids)
    return all_bids


class BoxScore(metaclass=decorators.CACHED):

    def __init__(self, boxscore_id):
        self.boxscore_id = boxscore_id

    def __eq__(self, other):
        return self.boxscore_id == other.boxscore_id

    def __hash__(self):
        return hash(self.boxscore_id)

    def __repr__(self):
        return 'BoxScore({})'.format(self.boxscore_id)

    def __str__(self):
        return '{} Week {}: {} @ {}'.format(
            self.season(), self.week(), self.away(), self.home()
        )

    def __reduce__(self):
        return BoxScore, (self.boxscore_id,)

    @decorators.memoize
    def get_doc(self):
        url = (PFR_BASE +
               '/boxscores/{}.htm'.format(self.boxscore_id))
        doc = pq(utils.get_html(url))
        return doc

    @decorators.memoize
    def get_game_info(self):
        doc = self.get_doc()
        table = doc('table#game_info')
        gi_table = utils.parse_info_table(table)
        return gi_table

    @decorators.memoize
    def date(self):
        """Returns the date of the game. See Python datetime.date documentation
        for more.
        :returns: A datetime.date object with year, month, and day attributes.
        """
        match = re.match(r'(\d{4})(\d{2})(\d{2})', self.boxscore_id)
        year, month, day = [int(m) for m in match.groups()]
        return datetime.date(year=year, month=month, day=day)

    @decorators.memoize
    def weekday(self):
        """Returns the day of the week on which the game occurred.
        :returns: String representation of the day of the week for the game.
        """
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                'Saturday', 'Sunday']
        date = self.date()
        wd = date.weekday()
        return days[wd]

    @decorators.memoize
    def stadium_info(self):
        """Returns a dict containing the stadium name and the attendance
        """
        doc = self.get_doc()
        meta = doc('div.scorebox_meta')
        regex = (
            r"(?:Stadium: (?P<stadium>[-.'&a-zA-Z ]+)\n),?\s*"
            r"(?:Attendance: (?P<attendance>[0-9,]+)\n)"
        )
        m = re.search(regex, meta.text())
        d = m.groupdict()
        if d['attendance'] is not None:
            d['attendance'] = int(d['attendance'].replace(',', ''))
        return d

    @decorators.memoize
    def home(self):
        """Returns home team ID.
        :returns: 3-character string representing home team's ID.
        """
        doc = self.get_doc()
        table = doc('table.linescore')
        rel_url = table('tr').eq(2)('a').eq(2).attr['href']
        home = utils.rel_url_to_id(rel_url)
        return home

    @decorators.memoize
    def away(self):
        """Returns away team ID.
        :returns: 3-character string representing away team's ID.
        """
        doc = self.get_doc()
        table = doc('table.linescore')
        rel_url = table('tr').eq(1)('a').eq(2).attr['href']
        away = utils.rel_url_to_id(rel_url)
        return away

    @decorators.memoize
    def home_score(self):
        """Returns score of the home team.
        :returns: int of the home score.
        """
        doc = self.get_doc()
        table = doc('table.linescore')
        home_score = table('tr').eq(2)('td')[-1].text_content()
        return int(home_score)

    @decorators.memoize
    def away_score(self):
        """Returns score of the away team.
        :returns: int of the away score.
        """
        doc = self.get_doc()
        table = doc('table.linescore')
        away_score = table('tr').eq(1)('td')[-1].text_content()
        return int(away_score)

    @decorators.memoize
    def coaches(self):
        """Returns a dict containing the id and name
        of the home and away HCs
        """
        doc = self.get_doc()
        coaches = doc('div.scorebox > div > div.datapoint > a')
        if len(coaches) != 2:
            print('Problem with fetching coaches')
            return {'home_hc_name': None, 'home_hc_id': None,
                    'away_hc_name': None, 'away_hc_id': None,}
        return {
            'home_hc_name': coaches[0].text,
            'home_hc_id': coaches[0].attrib['href'],
            'away_hc_name': coaches[1].text,
            'away_hc_id': coaches[1].attrib['href'],
        }

    @decorators.memoize
    def winner(self):
        """Returns the team ID of the winning team. Returns NaN if a tie."""
        hm_score = self.home_score()
        aw_score = self.away_score()
        if hm_score > aw_score:
            return self.home()
        elif hm_score < aw_score:
            return self.away()
        else:
            return None

    @decorators.memoize
    def week(self):
        """Returns the week in which this game took place. 18 is WC round, 19
        is Div round, 20 is CC round, 21 is SB.
        :returns: Integer from 1 to 21.
        """
        doc = self.get_doc()
        raw = doc('div#div_other_scores h2 a').attr['href']
        match = re.match(
            r'/years/{}/week_(\d+)\.htm'.format(self.season()), raw
        )
        if match:
            return int(match.group(1))
        else:
            return 21  # super bowl is week 21

    @decorators.memoize
    def season(self):
        """
        Returns the year ID of the season in which this game took place.
        Useful for week 17 January games.
        :returns: An int representing the year of the season.
        """
        date = self.date()
        return date.year - 1 if date.month <= 3 else date.year

    @decorators.memoize
    def starters(self):
        """Returns a DataFrame where each row is an entry in the starters table
        from PFR.
        The columns are:
        * player_id - the PFR player ID for the player (note that this column
        is not necessarily all unique; that is, one player can be a starter in
        multiple positions, in theory).
        * player_name - the listed name of the player; this too is not
        necessarily unique.
        * position - the position at which the player started for their team.
        * team - the team for which the player started.
        * home - True if the player's team was at home, False if they were away
        * offense - True if the player is starting on an offensive position,
        False if defense.
        :returns: A pandas DataFrame. See the description for details.
        """
        doc = self.get_doc()
        away = doc('table#vis_starters')
        home = doc('table#home_starters')
        data = []
        for h, table in enumerate((away, home)):
            team = self.home() if h else self.away()
            for i, row in enumerate(table('tbody tr').items()):
                datum = {}
                datum['player_id'] = utils.rel_url_to_id(
                    row('a')[0].attrib['href']
                )
                datum['player_name'] = row('th').text()
                datum['position'] = row('td').text()
                datum['team'] = team
                datum['home'] = (h == 1)
                datum['offense'] = (i <= 10)
                data.append(datum)
        return pd.DataFrame(data)

    @decorators.memoize
    def line(self):
        gi_table = self.get_game_info()
        line_text = gi_table.get('vegas_line', None)
        if line_text is None:
            return None
        m = re.match(r'(.+?) ([\-\.\d]+)$', line_text)
        if m:
            favorite, line = m.groups()
            line = float(line)
            # give in terms of the home team
            year = self.season()
            if favorite != teams.team_names(year)[self.home()]:
                line = -line
        else:
            line = 0
        return line

    @decorators.memoize
    def surface(self):
        """The playing surface on which the game was played.
        :returns: string representing the type of surface. Returns np.nan if
        not avaiable.
        """
        gi_table = self.get_game_info()
        return gi_table.get('surface', np.nan)


    @decorators.memoize
    def roof(self):
        """The playing surface on which the game was played.
        :returns: string representing the type of surface. Returns np.nan if
        not avaiable.
        """
        gi_table = self.get_game_info()
        return gi_table.get('roof')


    @decorators.memoize
    def over_under(self):
        """
        Returns the over/under for the game as a float, or np.nan if not
        available.
        """
        gi_table = self.get_game_info()
        if 'over_under' in gi_table:
            ou = gi_table['over_under']
            return float(ou.split()[0])
        else:
            return None

    @decorators.memoize
    def coin_toss(self):
        """Gets information relating to the opening coin toss.
        :returns: Dictionary of coin toss-related info.
        """
        gi_table = self.get_game_info()
        info = gi_table.get('won_toss')
        toss = {}
        toss['deferred'] = 'deferred' in info
        winner = info.split(' (')[0]
        winner_ot = gi_table.get('won_ot_toss')
        if winner in teams.team_names(self.season())[self.home()]:
            toss['toss_winner'] = self.home()
        else:
            toss['toss_winner'] = self.away()
        if winner_ot is None:
            toss['ot_toss_winner'] = None
        elif winner_ot.split(' (')[0] in teams.team_names(self.season())[self.home()]:
            toss['ot_toss_winner'] = self.home()
        else:
            toss['ot_toss_winner'] = self.away()
        return toss

    @decorators.memoize
    def weather(self):
        """Returns a dictionary of weather-related info.
        Keys of the returned dict:
        * temp
        * wind_chill
        * rel_humidity
        * wind_mph
        :returns: Dict of weather data.
        """
        gi_table = self.get_game_info()
        if 'weather' in gi_table:
            regex = (
                r'(?:(?P<temp>\-?\d+) degrees)?,?\s*'
                r'(?:relative humidity (?P<rel_humidity>\d+)%)?,?\s*'
                r'(?:wind (?P<wind_mph>\d+) mph)?,?\s*'
                r'(?:wind chill (?P<wind_chill>\-?\d+))?\s*'
            )
            m = re.match(regex, gi_table['weather'])
            d = m.groupdict()

            # cast values to int
            for k in d:
                try:
                    d[k] = int(d[k])
                except TypeError:
                    pass

            # one-off fixes
            d['wind_chill'] = (d['wind_chill'] if pd.notnull(d['wind_chill']) else d['temp'])
            d['wind_mph'] = d['wind_mph'] if pd.notnull(d['wind_mph']) else 0
            return d
        else:
            # no weather found, because it's a dome
            # TODO: what's relative humidity in a dome?
            return {
                'temp': None, 'wind_chill': None, 'rel_humidity': None, 'wind_mph': 0
            }

    @decorators.memoize
    def pbp(self):
        """Returns a dataframe of the play-by-play data from the game.
        Order of function calls:
            1. parse_table on the play-by-play table
            2. expand_details
                - calls parse_play_details & _clean_features
            3. _add_team_columns
            4. various fixes to clean data
            5. _add_team_features
        :returns: pandas DataFrame of play-by-play. Similar to GPF.
        """
        doc = self.get_doc()
        table = doc('table#pbp')
        df = utils.parse_table(table)
        # make the following features conveniently available on each row
        df['boxscore_id'] = self.boxscore_id
        df['home'] = self.home()
        df['away'] = self.away()
        df['season'] = self.season()
        df['week'] = self.week()
        feats = pbp.expand_details(df)

        # add team and opp columns by iterating through rows
        df = sportsref.nfl.pbp._add_team_columns(feats)
        # add WPA column (requires diff, can't be done row-wise)
        df['home_wpa'] = df.home_wp.diff()
        # lag score columns, fill in 0-0 to start
        for col in ('home_wp', 'pbp_score_hm', 'pbp_score_aw'):
            if col in df.columns:
                df[col] = df[col].shift(1)
        df.loc[0, ['pbp_score_hm', 'pbp_score_aw']] = 0
        # fill in WP NaN's
        df.home_wp.fillna(method='ffill', inplace=True)
        # fix first play border after diffing/shifting for WP and WPA
        firstPlaysOfGame = df[df.secsElapsed == 0].index
        line = self.line()
        for i in firstPlaysOfGame:
            initwp = sportsref.nfl.winProb.initialWinProb(line)
            df.loc[i, 'home_wp'] = initwp
            df.loc[i, 'home_wpa'] = df.loc[i + 1, 'home_wp'] - initwp
        # fix last play border after diffing/shifting for WP and WPA
        lastPlayIdx = df.index[-1]
        lastPlayWP = df.loc[lastPlayIdx, 'home_wp']
        # if a tie, final WP is 50%; otherwise, determined by winner
        winner = self.winner()
        finalWP = 50. if pd.isnull(winner) else (winner == self.home()) * 100.
        df.loc[lastPlayIdx, 'home_wpa'] = finalWP - lastPlayWP
        # fix WPA for timeouts and plays after timeouts
        timeouts = df[df.isTimeout].index
        for to in timeouts:
            df.loc[to, 'home_wpa'] = 0.
            if to + 2 in df.index:
                wpa = df.loc[to + 2, 'home_wp'] - df.loc[to + 1, 'home_wp']
            else:
                wpa = finalWP - df.loc[to + 1, 'home_wp']
            df.loc[to + 1, 'home_wpa'] = wpa
        # add team-related features to DataFrame
        df = sportsref.nfl.pbp._add_team_features(df)
        # fill distToGoal NaN's
        df['distToGoal'] = np.where(df.isKickoff, 65, df.distToGoal)
        df.distToGoal.fillna(method='bfill', inplace=True)
        df.distToGoal.fillna(method='ffill', inplace=True)  # for last play

        return df

    @decorators.memoize
    def ref_info(self):
        """Gets a dictionary of ref positions and the ref IDs of the refs for
        that game.
        :returns: A dictionary of ref positions and IDs.
        """
        doc = self.get_doc()
        table = doc('table#officials')
        return utils.parse_officials_table(table)

    @decorators.memoize
    def player_stats(self):
        """Gets the stats for offense, defense, returning, and kicking of
        individual players in the game.
        :returns: A DataFrame containing individual player stats.
        """
        doc = self.get_doc()
        table_ids = ('player_offense', 'player_defense', 'returns', 'kicking')
        dfs = []
        for tid in table_ids:
            table = doc('table#{}'.format(tid))
            dfs.append(utils.parse_table(table))
        dfs = [df for df in dfs if not df.empty]
        df = reduce(
            lambda x, y: pd.merge(
                x, y, how='outer', on=list(set(x.columns) & set(y.columns))
            ), dfs
        ).reset_index(drop=True)
        return df

    @decorators.memoize
    def snap_counts(self):
        """Gets the snap counts for both teams' players and returns them in a
        DataFrame. Note: only goes back to 2012.
        :returns: DataFrame of snap count data
        """
        # TODO: combine duplicate players, see 201312150mia - ThomDa03
        doc = self.get_doc()
        table_ids = ('vis_snap_counts', 'home_snap_counts')
        tms = (self.away(), self.home())
        df = pd.concat([
            utils.parse_table(doc('table#{}'.format(table_id)))
            .assign(is_home=bool(i), team=tms[i], opp=tms[i*-1+1])
            for i, table_id in enumerate(table_ids)
        ])
        if df.empty:
            return df
        return df.set_index('player_id')

    def full_meta(self):
        meta_dict = {
            **self.stadium_info(),
            **self.coin_toss(),
            **self.weather(),
            **self.coaches(),
            'roof': self.roof(),
            'home_line': self.line(),
            'ovr_und': self.over_under(),
            'surface': self.surface(),
            'season': self.season(),
            'week': self.week(),
            'home': self.home(),
            'away': self.away(),
            'box_id': self.boxscore_id,
        }
        ref_info = {
            k: v[1] for k, v in self.ref_info().items()
        }
        meta_dict.update(ref_info)
        return meta_dict
