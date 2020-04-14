import json
import os
import time
import collections
from urllib.parse import urlencode
import pandas as pd
from pyquery import PyQuery as pq

from nfl_stats import PFR_BASE
from .. import utils
from .. import pbp

__all__ = [
    'GamePlayFinder',
    'PlayerSeasonFinder', 'PlayerGameFinder', 'PlayerStreakFinder',
    'TeamGameFinder', 'TeamStreakFinder',
    'DriveFinder', 'DraftFinder',
]

class FinderObj():
    '''A base class for Finders from the Play Index.
    Subclasses must implement a "query" method'''
    # Subclasses must define these
    url_ext = None
    form_id = None
    opt_fname = None
    opt_dir = appdirs.user_data_dir('nfl_stats', getpass.getuser())
    extra_defs = {}

    def __init__(self):
        if None in [self.url_ext, self.form_id, self.opt_fname]:
            raise NotImplementedError(
                'FinderObj must be subclassed and [url, form_id, opt_fname] must be defined!')

        self.url = PFR_BASE + self.url_ext
        self.opt_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.opt_fname)
        self.inputs_with_defs = self._inputs_options_defaults()

    def __str__(self):
        return self.__class__.__name__

    def query(self, user_opts):
        raise NotImplementedError

    def get_querystring(self, user_opts):
        """Converts option dict given to finder object to a querystring.

        :returns: the querystring.
        """
        # start with defaults
        opts = {
            name: dct['value']
            for name, dct in self.inputs_with_defs.items()
        }

        # update keys based on the opt_dict
        for k, v in user_opts.items():
            if k not in opts:
                print('Skipping unrecognised paramter "{}" passed with value "{}"'.format(k, v))
            else:
                if isinstance(v, bool):
                    v = 'Y' if v else 'N'
                if isinstance(v, str):
                    v = v.split(',')
                # otherwise, make sure it's a list
                elif not isinstance(v, collections.Iterable):
                    v = [v]
                # then, add list of values to the querystring dict *opts*
                opts[k] = v

        opts['request'] = [1]

        return urlencode(opts, doseq=True)

    def show_options(self, defs=False):
        for opt, vals in self.inputs_with_defs.items():
            print('\033[1m{}\033[0m'.format(opt))
            if defs:
                print('Default: {}'.format(' '.join([str(v) for v in vals['value']])))
                if vals['options']:
                    print('Options: {}'.format(', '.join([str(o) for o in vals['options']])))

    def option(self, opt):
        vals = self.inputs_with_defs[opt]
        print('\033[1m{}\033[0m'.format(opt))
        print('Default: {}'.format(' '.join([str(v) for v in vals['value']])))
        if vals['options']:
            print('Options: {}'.format(', '.join([str(o) for o in vals['options']])))


    def _inputs_options_defaults(self):
        """Handles scraping options for play finder form.

        :returns: {'name1': {'value': val, 'options': [opt1, ...] }, ... }

        """
        # set time variables
        if os.path.isfile(self.opt_file):
            modtime = int(os.path.getmtime(self.opt_file))
            curtime = int(time.time())
        # if file found and it's been <= a week
        if (os.path.isfile(self.opt_file)
                and curtime - modtime <= 7 * 24 * 60 * 60):

            # just read the dict from the cached file
            with open(self.opt_file, 'r') as const_f:
                def_dict = json.load(const_f)

        # otherwise, we must regenerate the dict and rewrite it
        else:
            print('Regenerating {} Constants file'.format(str(self)))

            html = utils.get_html(self.url)
            doc = pq(html)

            def_dict = {}
            # start with input elements
            for inp in doc('form#{} input[name]'.format(self.form_id)):
                name = inp.attrib['name']
                # add blank dict if not present
                if name not in def_dict:
                    def_dict[name] = {
                        'value': set(),
                        'options': set(),
                        'type': inp.attrib['type']
                    }

                val = inp.attrib.get('value', '')
                # handle checkboxes and radio buttons
                if inp.type in ('checkbox', 'radio'):
                    # deal with default value
                    if 'checked' in inp.attrib:
                        def_dict[name]['value'].add(val)
                    # add to options
                    def_dict[name]['options'].add(val)
                # handle other types of inputs (only other type is hidden?)
                else:
                    def_dict[name]['value'].add(val)

            # for dropdowns (select elements)
            for sel in doc.items('form#{} select[name]'.format(self.form_id)):
                name = sel.attr['name']
                # add blank dict if not present
                if name not in def_dict:
                    def_dict[name] = {
                        'value': set(),
                        'options': set(),
                        'type': 'select'
                    }

                # deal with default value
                default_opt = sel('option[selected]')
                if len(default_opt):
                    default_opt = default_opt[0]
                    def_dict[name]['value'].add(default_opt.attrib.get('value', ''))
                else:
                    def_dict[name]['value'].add(
                        sel('option')[0].attrib.get('value', '')
                    )

                # deal with options
                def_dict[name]['options'] = {
                    opt.attrib['value'] for opt in sel('option')
                    if opt.attrib.get('value')
                }

            for k, v in self.extra_defs.items():
                if k not in def_dict:
                    def_dict[k] = {
                        'value': set(),
                        'options': set(),
                        'type': type(v).__name__
                    }
                def_dict[k]['value'] = [v]

            def_dict.pop('request', None)
            def_dict.pop('use_favorites', None)

            with open(self.opt_file, 'w+') as f:
                for k in def_dict:
                    try:
                        def_dict[k]['value'] = sorted(
                            list(def_dict[k]['value']), key=int
                        )
                        def_dict[k]['options'] = sorted(
                            list(def_dict[k]['options']), key=int
                        )
                    except ValueError:
                        def_dict[k]['value'] = sorted(list(def_dict[k]['value']))
                        def_dict[k]['options'] = sorted(list(def_dict[k]['options']))
                json.dump(def_dict, f)

        return def_dict


class GamePlayFinder(FinderObj):

    url_ext = '/play-index/play_finder.cgi'
    form_id = 'play_finder'
    opt_fname = 'GPFConstants.json'
    extra_defs = {'include_kneels' : 0}

    def query(self, user_opts, verbose=False):
        qargs = {**user_opts}
        querystring = self.get_querystring(qargs)
        url = '{}?{}'.format(self.url, querystring)
        # if verbose, print url
        if verbose:
            print(url)
        html = utils.get_html(url)
        doc = pq(html)

        # parse
        table = doc('table#all_plays')
        plays = utils.parse_table(table)

        # add parsed pbp info
        if 'description' in plays.columns:
            plays = pbp.expand_details(plays, detail_col='description')

        return plays


class PlayerSeasonFinder(FinderObj):
    '''Returns a list of tuples.
    For single seasons returns player and year.
    For total seasons returns player and count.
    For combined seasons returns player and min and max year'''

    url_ext = '/play-index/psl_finder.cgi'
    form_id = 'psl_finder'
    opt_fname = 'PSFConstants.json'
    extra_defs = {'offset' : 0}

    def query(self, user_opts, verbose=False):
        p_seasons = []
        qargs = {**user_opts}
        if 'offset' not in qargs:
            qargs['offset'] = 0

        while True:
            querystring = self.get_querystring(qargs)
            url = '{}?{}'.format(self.url, querystring)
            if verbose:
                print(url)
            html = utils.get_html(url)
            doc = pq(html)
            table = doc('table#results')
            df = utils.parse_table(table)
            if df.empty:
                break

            p_seasons.append(df)

            if doc('*:contains("Next Page")'):
                qargs['offset'] += 100
            else:
                break

        return pd.concat(p_seasons) if p_seasons else None


class PlayerGameFinder(FinderObj):

    url_ext = '/play-index/pgl_finder.cgi'
    form_id = 'pgl_finder'
    opt_fname = 'PGFConstants.json'
    extra_defs = {'offset' : 0}

    def query(self, user_opts, verbose=False):
        p_seasons = []
        qargs = {**user_opts}
        if 'offset' not in qargs:
            qargs['offset'] = 0

        while True:
            querystring = self.get_querystring(qargs)
            url = '{}?{}'.format(self.url, querystring)
            if verbose:
                print(url)
            html = utils.get_html(url)
            doc = pq(html)
            table = doc('table#results')
            df = utils.parse_table(table)
            if df.empty:
                break

            p_seasons.append(df)

            if doc('*:contains("Next Page")'):
                qargs['offset'] += 100
            else:
                break

        return pd.concat(p_seasons) if p_seasons else None


class PlayerStreakFinder(FinderObj):

    url_ext = '/play-index/player_streak_finder.cgi'
    form_id = 'streak_finder'
    opt_fname = 'PStrkFConstants.json'
    extra_defs = {}

    def query(self, user_opts, verbose=False):
        '''Takes a dict of options.
        Returns a dataframes containing streaks.
        Limited to top 100 matches.
        '''
        qargs = {**user_opts}
        querystring = self.get_querystring(qargs)
        url = '{}?{}'.format(self.url, querystring)
        # if verbose, print url
        if verbose:
            print(url)
        html = utils.get_html(url)
        doc = pq(html)

        # parse
        table = doc('table#player_streak')
        streaks = utils.parse_table(table)

        return streaks


class DriveFinder(FinderObj):

    url_ext = '/play-index/drive_finder.cgi'
    form_id = 'drive_finder'
    opt_fname = 'DrvFConstants.json'
    extra_defs = {}

    def query(self, user_opts, verbose=False):
        '''Takes a dict of options.
        Returns a tuple of dataframes containing drive information
        '''
        qargs = {**user_opts}
        querystring = self.get_querystring(qargs)
        url = '{}?{}'.format(self.url, querystring)
        # if verbose, print url
        if verbose:
            print(url)
        html = utils.get_html(url)
        doc = pq(html)

        # parse
        d_outcomes = utils.parse_table(doc('table#drive_outcomes'))
        d_totals = utils.parse_table(doc('table#drive_totals'))
        d_totals = d_totals.set_index('stat')
        def_drives = utils.parse_table(doc('table#defense_totals'))
        off_drives = utils.parse_table(doc('table#offense_totals'))

        return (d_outcomes, d_totals, def_drives, off_drives)


class TeamGameFinder(FinderObj):

    url_ext = '/play-index/tgl_finder.cgi'
    form_id = 'tgl_finder'
    opt_fname = 'TGFConstants.json'
    extra_defs = {'offset' : 0}

    def query(self, user_opts, verbose=False):
        t_games = []
        qargs = {**user_opts}
        if 'offset' not in qargs:
            qargs['offset'] = 0

        while True:
            querystring = self.get_querystring(qargs)
            url = '{}?{}'.format(self.url, querystring)
            if verbose:
                print(url)
            html = utils.get_html(url)
            doc = pq(html)
            table = doc('table#results')
            df = utils.parse_table(table)
            if df.empty:
                break

            t_games.append(df)

            if doc('*:contains("Next Page")'):
                qargs['offset'] += 100
            else:
                break

        all_games = pd.concat(t_games)

        return all_games


class TeamStreakFinder(FinderObj):

    url_ext = '/play-index/team_streak_finder.cgi'
    form_id = 'team_streak_finder'
    opt_fname = 'TSFConstants.json'
    extra_defs = {}

    def query(self, user_opts, verbose=False):
        '''Takes a dict of options.
        Returns a dataframes containing streaks.
        Limited to top 500 matches.
        '''
        qargs = {**user_opts}
        querystring = self.get_querystring(qargs)
        url = '{}?{}'.format(self.url, querystring)
        # if verbose, print url
        if verbose:
            print(url)
        html = utils.get_html(url)
        doc = pq(html)

        # parse
        table = doc('table#team_streak')
        streaks = utils.parse_table(table)

        return streaks


class DraftFinder(FinderObj):

    url_ext = '/play-index/draft-finder.cgi'
    form_id = 'draft_finder'
    opt_fname = 'DrftFConstants.json'
    extra_defs = {'offset' : 0}

    def query(self, user_opts, verbose=False):
        d_players = []
        qargs = {**user_opts}
        if 'offset' not in qargs:
            qargs['offset'] = 0

        while True:
            querystring = self.get_querystring(qargs)
            url = '{}?{}'.format(self.url, querystring)
            if verbose:
                print(url)
            html = utils.get_html(url)
            doc = pq(html)
            table = doc('table#results')
            df = utils.parse_table(table)
            if df.empty:
                break

            d_players.append(df)

            if doc('*:contains("Next Page")'):
                qargs['offset'] += 300
            else:
                break

        draftees = pd.concat(d_players, ignore_index=True)

        return draftees
