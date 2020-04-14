import numpy as np
from pyquery import PyQuery as pq

from nfl_stats import PFR_BASE
from . import teams
from . import utils
from . import decorators

__all__ = ['Season']


class Season(metaclass=decorators.CACHED):

    """Object representing a given NFL season."""

    def __init__(self, year):
        """Initializes a Season object for an NFL season.

        :year: The year of the season we want.
        """
        self.year = int(year)

    def __eq__(self, other):
        return self.year == other.year

    def __hash__(self):
        return hash(self.year)

    def __repr__(self):
        return 'Season({})'.format(self.year)

    def _subpage_url(self, page):
        return (PFR_BASE +
                '/years/{}/{}.htm'.format(self.year, page))

    @decorators.memoize
    def get_main_doc(self):
        """Returns PyQuery object for the main season URL.
        :returns: PyQuery object.
        """
        url = PFR_BASE + '/years/{}/'.format(self.year)
        return pq(utils.get_html(url))

    @decorators.memoize
    def get_sub_doc(self, subpage):
        """Returns PyQuery object for a given subpage URL.
        :subpage: The subpage of the season, e.g. 'per_game'.
        :returns: PyQuery object.
        """
        html = utils.get_html(self._subpage_url(subpage))
        return pq(html)

    @decorators.memoize
    def get_team_ids(self):
        """Returns a list of the team IDs for the given year.
        :returns: List of team IDs.
        """
        return teams.list_teams(self.year)

    @decorators.memoize
    def team_ids_to_names(self):
        """Mapping from 3-letter team IDs to full team names.

        :returns: Dictionary with team IDs as keys and full team strings as
            values.
        """
        return teams.team_names(self.year)

    @decorators.memoize
    def team_names_to_ids(self):
        """Mapping from full team names to 3-letter team IDs.
        :returns: Dictionary with tean names as keys and team IDs as values.
        """
        return teams.team_ids(self.year)

    @decorators.memoize
    def get_draft_info(self):
        """Returns a dataframe with draft info from the season.
        """
        url = (self._subpage_url('draft'))
        doc = pq(utils.get_html(url))
        table = doc('table#drafts')
        df = utils.parse_table(table)
        df['season'] = self.year
        df['season'] = df['season'].astype(int)
        cols = ['season', 'draft_round', 'draft_pick', 'team', 'player_id',
                'player_name', 'college_id', 'position', 'age']
        for col in cols:
            if col not in df: df[col] = np.nan
        df = df[cols]
        return df

    @decorators.memoize
    def _get_player_stats_table(self, subpage, table_id):
        """Helper function for player season stats.

        :identifier: string identifying the type of stat, e.g. 'passing'.
        :returns: A DataFrame of stats.
        """
        doc = self.get_sub_doc(subpage)
        table = doc('table#{}'.format(table_id))
        df = utils.parse_table(table)
        return df

    def player_stats_passing(self):
        """Returns a DataFrame of passing player stats for a season."""
        return self._get_player_stats_table('passing', 'passing')

    def player_stats_rushing(self):
        """Returns a DataFrame of rushing player stats for a season."""
        return self._get_player_stats_table('rushing', 'rushing_and_receiving')

    def player_stats_receiving(self):
        """Returns a DataFrame of receiving player stats for a season."""
        return self._get_player_stats_table('receiving', 'receiving')

    @decorators.memoize
    def _get_week_links(self):
        """Fetches links to boxscores for all weeks in season"""
        doc = self.get_main_doc()
        week_a = doc('div#div_week_games')('a')
        week_lnks = {}
        for l in week_a.items():
            week_lnks[l.text()] = l.attr['href']
        return week_lnks

    def get_box_scores(self):
        pass

    @decorators.memoize
    def get_year_info(self):
        doc = self.get_main_doc()
        meta = doc('div#meta')
        data = [p for p in meta('p').items() if p('strong').text()]
        info = {}
        for d in data:
            k, _, v = d.text().partition(':')
            info[k.strip()] = v.strip()


