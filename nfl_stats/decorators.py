import copy
import datetime
import getpass
import hashlib
import os
import re
import time
import appdirs
from boltons import funcutils
import mementos
from pyquery import PyQuery as pq

def _days_valid_pfr(url):
    # boxscores are static, but refresh quarterly to be sure
    if 'boxscore' in url:
        return 90
    # important dates
    today = datetime.date.today()
    start_of_season = datetime.date(today.year, 8, 15)
    end_of_season = datetime.date(today.year, 2, 15)
    # check for a year in the filename
    m = re.search(r'(\d{4})', url)
    if m:
        # if it was a year prior to the current season, we're good
        year = int(m.group(1))
        cur_season = today.year - (today <= end_of_season)
        if year < cur_season:
            return 90
    # if it's the offseason, refresh cache twice a month
    if end_of_season < today < start_of_season:
        return 15
    # otherwise, refresh every 2 days
    return 2


def cache_html(func):
    """Caches the HTML returned by the specified function `func`. Caches it in
    the user cache determined by the appdirs package.
    """

    cache_dir = appdirs.user_cache_dir('nfl_stats', getpass.getuser())
    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir)

    @funcutils.wraps(func)
    def wrapper(url, *args, **kwargs):
        # hash based on the URL
        file_hash = hashlib.md5()
        encoded_url = url.encode(errors='replace')
        file_hash.update(encoded_url)
        file_hash = file_hash.hexdigest()
        filename = '{}/{}'.format(cache_dir, file_hash)

        if url.startswith(
            ('https://www.pro-football-reference.com',
             'http://www.nflpenalties.com',
             'https://www.teamrankings.com/nfl/')):
            sport_id = 'pfr'
        else:
            print('No sport ID found for {}, not able to check cache'.format(url))

        # check whether cache is valid or stale
        file_exists = os.path.isfile(filename)
        if sport_id and file_exists:
            cur_time = int(time.time())
            mod_time = int(os.path.getmtime(filename))
            days_since_mod = datetime.timedelta(seconds=(cur_time - mod_time)).days
            days_cache_valid = globals()['_days_valid_{}'.format(sport_id)](url)
            cache_is_valid = days_since_mod < days_cache_valid
        else:
            cache_is_valid = False

        # if file found and cache is valid, read from file
        if file_exists and cache_is_valid:
            with open(filename, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        # otherwise, execute function and cache results
        else:
            text = func(url)
            with open(filename, 'w+', encoding='utf-8') as f:
                f.write(text)
        return text

    return wrapper


def get_class_instance_key(cls, args, kwargs):
    """
    Returns a unique identifier for a class instantiation.
    """
    l = [id(cls)]
    for arg in args:
        l.append(id(arg))
    l.extend((k, id(v)) for k, v in kwargs.items())
    return tuple(sorted(l))


# used as a metaclass for classes that should be memoized
# (technically not a decorator, but it's similar enough)
CACHED = mementos.memento_factory('Cached', get_class_instance_key)


def memoize(fun):
    """A decorator for memoizing functions.

    Only works on functions that take simple arguments - arguments that take
    list-like or dict-like arguments will not be memoized, and this function
    will raise a TypeError.
    """
    @funcutils.wraps(fun)
    def wrapper(*args, **kwargs):

        hash_args = tuple(args)
        hash_kwargs = frozenset(sorted(kwargs.items()))
        key = (hash_args, hash_kwargs)

        def _copy(v):
            if isinstance(v, pq):
                return v.clone()
            else:
                return copy.deepcopy(v)

        try:
            ret = _copy(cache[key])
            return ret
        except KeyError:
            cache[key] = fun(*args, **kwargs)
            ret = _copy(cache[key])
            return ret
        except TypeError:
            print('memoization type error in function {} for arguments {}'
                  .format(fun.__name__, key))
            raise

    cache = {}
    return wrapper
