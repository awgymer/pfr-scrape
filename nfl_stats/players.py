import re
import datetime
from urllib.parse import urljoin
import pandas as pd
from pyquery import PyQuery as pq

from nfl_stats import PFR_BASE
from . import utils
from . import decorators
from . import pbp

__all__ = [
    'Player', 'PlayerColumnNotFound',
]

class PlayerColumnNotFound(Exception):
    pass


class AVStatNotFound(Exception):
    pass


class Player(metaclass=decorators.CACHED):

    def __init__(self, player_id):
        self.base_url = PFR_BASE + '/players/{p[0]}/{p}.htm'.format(p=player_id)
        self.id_str = player_id

    def __eq__(self, other):
        return self.id_str == other.id_str

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.id_str)

    def __repr__(self):
        return 'Player({})'.format(self.id_str)

    def __reduce__(self):
        return Player, (self.id_str,)

    def _sub_url(self, page, year=None):
        # if no year, return career version
        if year is None:
            return urljoin(self.base_url, '{}/{}/'.format(self.id_str, page))
        # otherwise, return URL for a given year
        else:
            return urljoin(self.base_url, '{}/{}/{}/'.format(self.id_str, page, year))

    @decorators.memoize
    def get_doc(self):
        doc = pq(utils.get_html(self.base_url))
        return doc

    @property
    @decorators.memoize
    def name(self):
        doc = self.get_doc()
        name = doc('div#meta h1:first').text()
        return name

    @decorators.memoize
    def age(self, year, month=9, day=1):
        '''Return a players age on a given date
        Defaults to their age on Sep 1 (Season start)
        '''
        doc = self.get_doc()
        span = doc('div#meta span#necro-birth')
        birthstring = span.attr('data-birth')
        try:
            dateargs = re.match(r'(\d{4})\-(\d{2})\-(\d{2})',
                                birthstring).groups()
            dateargs = [int(d) for d in dateargs]
            birth_date = datetime.date(*dateargs)
            delta = datetime.date(year=year, month=month, day=day) - birth_date
            age = delta.days / 365
            return age
        except Exception:
            return None

    @property
    @decorators.memoize
    def position(self):
        doc = self.get_doc()
        raw_text = doc('div#meta p').filter(lambda i, e: 'Position' in e.text_content()).text()
        raw_pos = re.search(r'Position\W*(\S+)', raw_text, re.I).group(1)
        all_pos = raw_pos.split('-')
        # right now, returning just the primary position for those with
        # multiple positions
        return all_pos[0]

    @property
    @decorators.memoize
    def height(self):
        doc = self.get_doc()
        raw_text = doc('div#meta p span[itemprop="height"]').text()
        try:
            feet, inches = [int(d) for d in raw_text.split('-')]
            return feet * 12 + inches
        except ValueError:
            return None

    @property
    @decorators.memoize
    def weight(self):
        doc = self.get_doc()
        raw_text = doc('div#meta p span[itemprop="weight"]').text()
        try:
            weight = re.match(r'(\d+)lb', raw_text, re.I).group(1)
            return int(weight)
        except AttributeError:
            return None

    @property
    @decorators.memoize
    def hand(self):
        doc = self.get_doc()
        try:
            raw_text = doc('div#meta p').filter(lambda i, e: 'Throws' in e.text_content()).text()
            raw_hand = re.search(r'Throws\W+(\S+)', raw_text, re.I).group(1)
        except AttributeError:
            return None
        return raw_hand[0]  # 'L' or 'R'

    @property
    @decorators.memoize
    def current_team(self):
        doc = self.get_doc()
        team = doc('div#meta p').filter(lambda i, e: 'Team' in e.text_content())
        text = utils.flatten_links(team)
        m = re.match(r'Team: (\w{3})', text)
        if m:
            return m.group(1)
        return None

    @property
    @decorators.memoize
    def draft_pick(self):
        doc = self.get_doc()
        raw_draft = doc('div#meta p').filter(lambda i, e: 'Draft' in e.text_content()).text()
        m = re.search(r'Draft.*? round \((\d+).*?overall\)', raw_draft, re.I)
        # if not drafted or taken in supplemental draft, return NaN
        if m is None or 'Supplemental' in raw_draft:
            return None
        return int(m.group(1))

    @property
    @decorators.memoize
    def draft_class(self):
        doc = self.get_doc()
        raw_draft = doc('div#meta p').filter(lambda i, e: 'Draft' in e.text_content()).text()
        m = re.search(r'Draft.*?of the (\d{4}) NFL', raw_draft, re.I)
        if m:
            return int(m.group(1))
        return None


    @property
    @decorators.memoize
    def draft_team(self):
        doc = self.get_doc()
        raw_draft = doc('div#meta p').filter(lambda i, e: 'Draft' in e.text_content())
        draft_str = utils.flatten_links(raw_draft)
        m = re.search(r'Draft\W+(\w+)', draft_str)
        if m:
            return m.group(1)
        return None

    @property
    @decorators.memoize
    def college(self):
        doc = self.get_doc()
        raw_text = doc('div#meta p').filter(lambda i, e: 'College' in e.text_content())
        cleaned_text = utils.flatten_links(raw_text)
        m = re.search(r'College:\s*(\S+)', cleaned_text)
        if m:
            return m.group(1)
        return None

    @property
    @decorators.memoize
    def high_school(self):
        doc = self.get_doc()
        raw_text = doc('div#meta p').filter(lambda i, e: 'High School' in e.text_content())
        cleaned_text = utils.flatten_links(raw_text)
        m = re.search(r'High School:\s*(\S+)', cleaned_text)
        if m:
            return m.group(1)
        return None

    @decorators.memoize
    def get_gamelogs(self, year=None):
        '''Gets the career gamelogs for player.
        :years: An int year to get data for.
        :returns: A dataframe of career gamelogs
        '''
        pq_html = pq(
            utils.get_html(self._sub_url('gamelog', year))
        )
        reg = utils.parse_table(pq_html('table#stats'))
        poff = utils.parse_table(pq_html('table#stats_playoffs'))
        reg['is_playoff'] = False
        if not poff.empty:
            poff['is_playoff'] = True
        all_g = pd.concat((reg, poff), ignore_index=True)
        all_g['name'] = self.name
        return all_g

    @decorators.memoize
    def get_fantasy_stats(self, year=None):
        '''Gets the career fantasy stats for player.
        :years: An int year to get data for.
        :returns: A dataframe of career gamelogs
        '''
        pq_html = pq(
            utils.get_html(self._sub_url('fantasy', year))
        )
        fan_stats = utils.parse_table(pq_html('table#player_fantasy'))
        fan_stats['name'] = self.name
        return fan_stats

    @decorators.memoize
    def get_av_stats(self):
        doc = self.get_doc()
        table = doc('th[data-stat=av]').parents('table')
        if not table:
            raise AVStatNotFound()
        seasons = utils.parse_table(table)
        seasons['name'] = self.name
        return seasons[['name', 'year', 'team_id', 'team', 'g', 'gs', 'av']]

    @decorators.memoize
    def passing(self, partial=False):
        """Gets yearly passing stats for the player.
        :returns: Pandas DataFrame with passing stats.
        """
        doc = self.get_doc()
        reg = utils.parse_table(doc('table#passing'), partial=partial)
        poff = utils.parse_table(doc('table#passing_playoffs'), partial=partial)
        reg['is_playoff'] = False
        if not poff.empty:
            poff['is_playoff'] = True
        all_df = pd.concat((reg, poff), ignore_index=True)
        all_df['name'] = self.name
        return all_df

    @decorators.memoize
    def rushing_and_receiving(self, partial=False):
        """Gets yearly rushing/receiving stats for the player.
        :returns: Pandas DataFrame with rushing/receiving stats.
        """
        doc = self.get_doc()
        reg = utils.parse_table(doc('table#rushing_and_receiving'), partial=partial)
        poff = utils.parse_table(doc('table#rushing_and_receiving_playoffs'), partial=partial)
        if reg.empty:
            reg = utils.parse_table(doc('table#receiving_and_rushing'), partial=partial)
            poff = utils.parse_table(doc('table#receiving_and_rushing_playoffs'), partial=partial)
        reg['is_playoff'] = False
        if not poff.empty:
            poff['is_playoff'] = True
        all_df = pd.concat((reg, poff), ignore_index=True)
        all_df['name'] = self.name
        return all_df

    @decorators.memoize
    def defense(self, partial=False):
        """Gets yearly defense stats for the player (also has AV stats for OL).
        :returns: Pandas DataFrame with rushing/receiving stats.
        """
        doc = self.get_doc()
        reg = utils.parse_table(doc('table#defense'), partial=partial)
        poff = utils.parse_table(doc('table#defense_playoffs'), partial=partial)
        reg['is_playoff'] = False
        if not poff.empty:
            poff['is_playoff'] = True
        all_df = pd.concat((reg, poff), ignore_index=True)
        all_df['name'] = self.name
        return all_df

    def _plays(self, year, play_type, expand_details):
        """Returns a DataFrame of plays for a given year for a given play type
        (like rushing, receiving, or passing).
        :year: The year for the season.
        :play_type: A type of play for which there are plays (as of this
        writing, either "passing", "rushing", or "receiving")
        :expand_details: Bool for whether PBP should be parsed.
        :returns: A DataFrame of plays, each row is a play. Returns None if
        there were no such plays in that year.
        """
        url = self._sub_url('{}-plays'.format(play_type), year)
        doc = pq(utils.get_html(url))
        table = doc('table#all_plays')
        if table:
            if expand_details:
                plays = pbp.expand_details(utils.parse_table(table), detail_col='description')
                return plays
            else:
                return utils.parse_table(table)
        else:
            return None

    @decorators.memoize
    def passing_plays(self, year, expand_details=True):
        """Returns a pbp DataFrame of a player's passing plays in a season.
        :year: The year for the season.
        :expand_details: bool for whether PBP should be parsed.
        :returns: A DataFrame of stats, each row is a play.
        """
        return self._plays(year, 'passing', expand_details)

    @decorators.memoize
    def rushing_plays(self, year, expand_details=True):
        """Returns a pbp DataFrame of a player's rushing plays in a season.
        :year: The year for the season.
        :expand_details: bool for whether PBP should be parsed.
        :returns: A DataFrame of stats, each row is a play.
        """
        return self._plays(year, 'rushing', expand_details)

    @decorators.memoize
    def receiving_plays(self, year, expand_details=True):
        """Returns a pbp DataFrame of a player's receiving plays in a season.
        :year: The year for the season.
        :expand_details: bool for whether PBP should be parsed.
        :returns: A DataFrame of stats, each row is a play.
        """
        return self._plays(year, 'receiving', expand_details)

    @decorators.memoize
    def splits(self, year=None):
        """Returns a DataFrame of splits data for a player-year.
        :year: The year for the season in question. If None, returns career
        splits.
        :returns: A DataFrame of splits data.
        """
        # get the table
        url = self._sub_url('splits', year)
        doc = pq(utils.get_html(url))
        table = doc('table#stats')
        df = utils.parse_table(table)
        # cleaning the data
        if not df.empty:
            df.split_id.fillna(method='ffill', inplace=True)
        return df

    @decorators.memoize
    def advanced_splits(self, year=None):
        """Returns a DataFrame of advanced splits data for a player-year. Note:
            only go back to 2012.
        :year: The year for the season in question. If None, returns career
        advanced splits.
        :returns: A DataFrame of advanced splits data.
        """
        # get the table
        url = self._sub_url('splits', year)
        doc = pq(utils.get_html(url))
        table = doc('table#advanced_splits')
        df = utils.parse_table(table)
        # cleaning the data
        if not df.empty:
            df.split_type.fillna(method='ffill', inplace=True)
        return df

    @decorators.memoize
    def _simple_year_award(self, award_id):
        """Template for simple award functions that simply list years, such as
        pro bowls and first-team all pro.

        :award_id: The div ID that is appended to "leaderboard_" in selecting
        the table's div.
        :returns: List of years for the award.
        """
        doc = self.get_doc()
        table = doc('div#leaderboard_{} table'.format(award_id))
        return [int(y) for y in utils.parse_awards_table(table)]

    @property
    def pro_bowls(self):
        """Returns a list of years in which the player made the Pro Bowl."""
        return self._simple_year_award('pro_bowls')

    @property
    def first_team_all_pros(self):
        """Returns a list of years in which the player made 1st-Tm All Pro."""
        return self._simple_year_award('all_pro')
