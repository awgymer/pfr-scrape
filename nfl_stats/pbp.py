import copy
import re

import numpy as np
import pandas as pd

RUSH_OPTS = {
    'left end': 'LE', 'left tackle': 'LT', 'left guard': 'LG',
    'up the middle': 'M', 'middle': 'M',
    'right end': 'RE', 'right tackle': 'RT', 'right guard': 'RG',
}
PASS_OPTS = {
    'short left': 'SL', 'short middle': 'SM', 'short right': 'SR',
    'deep left': 'DL', 'deep middle': 'DM', 'deep right': 'DR',
}


def expand_details(df, detail_col='detail'):
    """Expands the details column of the given dataframe and returns the
    resulting DataFrame.

    :df: The input DataFrame.
    :detail_col: The detail column name.
    :returns: Returns DataFrame with new columns from pbp parsing.
    """
    df = copy.deepcopy(df)
    df['detail'] = df[detail_col]
    dicts = [parse_play_details(detail) for detail in df['detail'].values]
    # clean up unmatched details
    cols = {c for d in dicts if d for c in d.keys()}
    blank_entry = {c: np.nan for c in cols}
    new_dicts = [d if d else blank_entry for d in dicts]
    # get details DataFrame and merge it with original to create main DataFrame
    details = pd.DataFrame(new_dicts)
    df = pd.merge(df, details, left_index=True, right_index=True)
    # add is_error column
    errors = [i for i, d in enumerate(dicts) if d is None]
    df['is_error'] = False
    df.loc[errors, 'is_error'] = True
    # fill in some NaN's necessary for _clean_features
    df.loc[0, 'qtr_time_remain'] = '15:00'
    df.qtr_time_remain.fillna(method='bfill', inplace=True)
    df.qtr_time_remain.fillna(
        pd.Series(np.where(df.quarter == 4, '0:00', '15:00')), inplace=True
    )
    # use _clean_features to clean up and add columns
    new_df = df.apply(_clean_features, axis=1)
    return new_df


def parse_play_details(details):
    """Parses play details from play-by-play string and returns structured
    data.

    :details: detail string for play
    :returns: dictionary of play attributes
    """

    # if input isn't a string, return None
    if not isinstance(details, str):
        return None

    rushOptRE = r'(?P<rushDir>{})'.format(
        r'|'.join(RUSH_OPTS.keys())
    )
    passOptRE = r'(?P<passLoc>{})'.format(
        r'|'.join(PASS_OPTS.keys())
    )

    playerRE = r"\S{6,8}\d{2}"

    # initialize return dictionary - struct
    struct = {}

    # handle challenges
    # TODO: record the play both before & after an overturned challenge
    challengeRE = re.compile(
        r'.+\. (?P<challenger>.+?) challenged.*? the play was (?P<callUpheld>upheld|overturned)\.',
        re.IGNORECASE
    )
    match = challengeRE.search(details)
    if match:
        struct['isChallenge'] = True
        struct.update(match.groupdict())
        # if overturned, only record updated play
        if 'overturned' in details:
            overturned_idx = details.index('overturned.')
            new_start = overturned_idx + len('overturned.')
            details = details[new_start:].strip()
    else:
        struct['isChallenge'] = False

    # TODO: expand on laterals
    struct['isLateral'] = details.find('lateral') != -1

    # create rushing regex
    rusherRE = r"(?P<rusher>{0})".format(playerRE)
    rushOptRE = r"(?: {})?".format(rushOptRE)
    rushYardsRE = r"(?:(?:(?P<rushYds>\-?\d+) yards?)|(?:no gain))"
    # cases: tackle, fumble, td, penalty
    tackleRE = (r"(?: \(tackle by (?P<tackler1>{0})"
                r"(?: and (?P<tackler2>{0}))?\))?"
                .format(playerRE))
    # currently, plays with multiple fumbles record the original fumbler
    # and the final fumble recoverer
    fumbleRE = (
        r"(?:"
        r"\.? ?(?P<fumbler>{0}) fumbles"
        r"(?: \(forced by (?P<fumbForcer>{0})\))?"
        r"(?:.*, recovered by (?P<fumbRecoverer>{0}) at )?"
        r"(?:, ball out of bounds at )?"
        r"(?:(?P<fumbRecFieldSide>[a-z]+)?\-?(?P<fumbRecYdLine>\-?\d+))?"
        r"(?: and returned for (?P<fumbRetYds>\-?\d*) yards)?"
        r")?"
        .format(playerRE))
    tdSafetyRE = r"(?:(?P<isTD>, touchdown)|(?P<isSafety>, safety))?"
    # TODO: offsetting penalties
    penaltyRE = (r"(?:.*?"
                 r"\. Penalty on (?P<penOn>{0}|): "
                 r"(?P<penalty>[^\(,]+)"
                 r"(?: \((?P<penDeclined>Declined)\)|"
                 r", (?P<penYds>\d*) yards?)"
                 r"(?: \(no play\))?"
                 r")?"
                 .format(playerRE))

    rushREstr = (
        r"{}{}(?: for {}{}{}{}{})?"
    ).format(rusherRE, rushOptRE, rushYardsRE, tackleRE, fumbleRE, tdSafetyRE,
             penaltyRE)
    rushRE = re.compile(rushREstr, re.IGNORECASE)

    # create passing regex
    # TODO: capture "defended by X" for defensive stats
    passerRE = r"(?P<passer>{0})".format(playerRE)
    sackRE = (r"(?:sacked (?:by (?P<sacker1>{0})(?: and (?P<sacker2>{0}))? )?"
              r"for (?P<sackYds>\-?\d+) yards?)"
              .format(playerRE))
    # create throw RE
    completeRE = r"pass (?P<isComplete>(?:in)?complete)"
    passOptRE = r"(?: {})?".format(passOptRE)
    targetedRE = r"(?: (?:to |intended for )?(?P<target>{0}))?".format(
        playerRE)
    passYardsRE = r"(?: for (?:(?P<passYds>\-?\d+) yards?|no gain))"
    intRE = (r'(?: is intercepted by (?P<interceptor>{0}) at '.format(playerRE)
             + r'(?:(?P<intFieldSide>[a-z]*)?\-?(?P<intYdLine>\-?\d*))?'
             + r'(?: and returned for (?P<intRetYds>\-?\d+) yards?\.?)?)?')
    throwRE = r'(?:{}{}{}(?:(?:{}|{}){})?)'.format(
        completeRE, passOptRE, targetedRE, passYardsRE, intRE, tackleRE
    )
    passREstr = (
        r"{} (?:{}|{})(?:{}{}{})?"
    ).format(passerRE, sackRE, throwRE, fumbleRE, tdSafetyRE, penaltyRE)
    passRE = re.compile(passREstr, re.IGNORECASE)

    # create kickoff regex
    koKickerRE = r'(?P<koKicker>{0})'.format(playerRE)
    koYardsRE = (r' kicks (?:off|(?P<isOnside>onside))'
                 r' (?:(?P<koYds>\d+) yards?|no gain)')
    nextREs = []
    nextREs.append(
        (r', (?:returned|recovered) by (?P<koReturner>{0})(?: for '
         r'(?:(?P<koRetYds>\-?\d+) yards?|no gain))?').format(playerRE)
    )
    nextREs.append(
        (r'(?P<isMuffedCatch>, muffed catch by )(?P<muffedBy>{0}),'
         r'(?: recovered by (?P<muffRecoverer>{0}))?').format(playerRE) +
        r'(?: and returned for (?:(?P<muffRetYds>\-?\d+) yards|no gain))?'
    )
    nextREs.append(
        r', recovered by (?P<onsideRecoverer>{0})'.format(playerRE)
    )
    nextREs.append(r'(?P<oob>, out of bounds)')
    nextREs.append(r'(?P<isTouchback>, touchback)')
    # TODO: test the following line to fix a small subset of cases
    # (ex: muff -> oob)
    nextRE = ''.join(r'(?:{})?'.format(nre) for nre in nextREs)
    kickoffREstr = r'{}{}{}{}{}{}{}'.format(
        koKickerRE, koYardsRE, nextRE,
        tackleRE, fumbleRE, tdSafetyRE, penaltyRE
    )
    kickoffRE = re.compile(kickoffREstr, re.IGNORECASE)

    # create timeout regex
    timeoutREstr = r'Timeout #(?P<timeoutNum>\d) by (?P<timeoutTeam>.+)'
    timeoutRE = re.compile(timeoutREstr, re.IGNORECASE)

    # create FG regex
    fgKickerRE = r'(?P<fgKicker>{0})'.format(playerRE)
    fgBaseRE = (r' (?P<fgDist>\d+) yard field goal'
                r' (?P<fgGood>good|no good)')
    fgBlockRE = (
        r'(?:, (?P<isBlocked>blocked) by '
        r'(?P<fgBlocker>{0}))?'.format(playerRE) +
        r'(?:, recovered by (?P<fgBlockRecoverer>{0}))?'.format(playerRE) +
        r'(?: and returned for (?:(?P<fgBlockRetYds>\-?\d+) yards?|no gain))?'
    )
    fgREstr = r'{}{}{}{}{}'.format(fgKickerRE, fgBaseRE,
                                   fgBlockRE, tdSafetyRE, penaltyRE)
    fgRE = re.compile(fgREstr, re.IGNORECASE)

    # create punt regex
    punterRE = r'.*?(?P<punter>{0})'.format(playerRE)
    puntBlockRE = (
        (r' punts, (?P<isBlocked>blocked) by (?P<puntBlocker>{0})'
         r'(?:, recovered by (?P<puntBlockRecoverer>{0})').format(playerRE) +
        r'(?: and returned (?:(?P<puntBlockRetYds>\-?\d+) yards|no gain))?)?'
    )
    puntYdsRE = r' punts (?P<puntYds>\d+) yards?'
    nextREs = []
    nextREs.append(r', (?P<isFairCatch>fair catch) by (?P<fairCatcher>{0})'
                   .format(playerRE))
    nextREs.append(r', (?P<oob>out of bounds)')
    nextREs.append(
        (r'(?P<isMuffedCatch>, muffed catch by )(?P<muffedBy>{0}),'
         r' recovered by (?P<muffRecoverer>{0})').format(playerRE) +
        r' and returned for ' +
        r'(?:(?P<muffRetYds>\d+) yards|no gain)'
    )
    nextREs.append(
        r', returned by (?P<puntReturner>{0}) for '.format(playerRE) +
        r'(?:(?P<puntRetYds>\-?\d+) yards?|no gain)'
    )
    nextREs.append(r'(?P<isTouchback>, touchback)')
    nextRE = r'(?:{})?'.format('|'.join(nextREs))
    puntREstr = r'{}(?:{}|{}){}{}{}{}{}'.format(
        punterRE, puntBlockRE, puntYdsRE, nextRE,
        tackleRE, fumbleRE, tdSafetyRE, penaltyRE
    )
    puntRE = re.compile(puntREstr, re.IGNORECASE)

    # create kneel regex
    kneelREstr = (r'(?P<kneelQB>{0}) kneels for '.format(playerRE) +
                  r'(?:(?P<kneelYds>\-?\d+) yards?|no gain)')
    kneelRE = re.compile(kneelREstr, re.IGNORECASE)

    # create spike regex
    spikeREstr = r'(?P<spikeQB>{0}) spiked the ball'.format(playerRE)
    spikeRE = re.compile(spikeREstr, re.IGNORECASE)

    # create XP regex
    extraPointREstr = (r'(?:(?P<xpKicker>{0}) kicks)? ?extra point '
                       r'(?P<xpGood>good|no good)').format(playerRE)
    extraPointRE = re.compile(extraPointREstr, re.IGNORECASE)

    # create 2pt conversion regex
    twoPointREstr = (
        r'Two Point Attempt: (?P<twoPoint>.*?),?\s+conversion\s+'
        r'(?P<twoPointSuccess>succeeds|fails)'
    )
    twoPointRE = re.compile(twoPointREstr, re.IGNORECASE)

    # create penalty regex
    psPenaltyREstr = (
        r'^Penalty on (?P<penOn>{0}|'.format(playerRE) + r'\w{3}): ' +
        r'(?P<penalty>[^\(,]+)(?: \((?P<penDeclined>Declined)\)|' +
        r', (?P<penYds>\d*) yards?|' +
        r'.*?(?: \(no play\)))')
    psPenaltyRE = re.compile(psPenaltyREstr, re.IGNORECASE)

    # try parsing as a kickoff
    match = kickoffRE.search(details)
    if match:
        # parse as a kickoff
        struct['isKickoff'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a timeout
    match = timeoutRE.search(details)
    if match:
        # parse as timeout
        struct['isTimeout'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a field goal
    match = fgRE.search(details)
    if match:
        # parse as a field goal
        struct['isFieldGoal'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a punt
    match = puntRE.search(details)
    if match:
        # parse as a punt
        struct['isPunt'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a kneel
    match = kneelRE.search(details)
    if match:
        # parse as a kneel
        struct['isKneel'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a spike
    match = spikeRE.search(details)
    if match:
        # parse as a spike
        struct['isSpike'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as an XP
    match = extraPointRE.search(details)
    if match:
        # parse as an XP
        struct['isXP'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a 2-point conversion
    match = twoPointRE.search(details)
    if match:
        # parse as a 2-point conversion
        struct['isTwoPoint'] = True
        struct['twoPointSuccess'] = match.group('twoPointSuccess')
        realPlay = parse_play_details(
            match.group('twoPoint'))
        if realPlay:
            struct.update(realPlay)
        return struct

    # try parsing as a pass
    match = passRE.search(details)
    if match:
        # parse as a pass
        struct['isPass'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a pre-snap penalty
    match = psPenaltyRE.search(details)
    if match:
        # parse as a pre-snap penalty
        struct['isPresnapPenalty'] = True
        struct.update(match.groupdict())
        return struct

    # try parsing as a run
    match = rushRE.search(details)
    if match:
        # parse as a run
        struct['isRun'] = True
        struct.update(match.groupdict())
        return struct

    return None


def _clean_features(struct):
    """Cleans up the features collected in parse_play_details.

    :struct: Pandas Series of features parsed from details string.
    :returns: the same dict, but with cleaner features (e.g., convert bools,
    ints, etc.)
    """
    struct = dict(struct)
    # First, clean up play type bools
    ptypes = ['isKickoff', 'isTimeout', 'isFieldGoal', 'isPunt', 'isKneel',
              'isSpike', 'isXP', 'isTwoPoint', 'isPresnapPenalty', 'isPass',
              'isRun', 'penalty']
    for pt in ptypes:
        struct[pt] = struct[pt] if pd.notnull(struct.get(pt)) else False
    # Second, clean up other existing variables on a one-off basis
    struct['callUpheld'] = struct.get('callUpheld') == 'upheld'
    struct['fgGood'] = struct.get('fgGood') == 'good'
    struct['isBlocked'] = struct.get('isBlocked') == 'blocked'
    struct['isComplete'] = struct.get('isComplete') == 'complete'
    struct['isFairCatch'] = struct.get('isFairCatch') == 'fair catch'
    struct['isMuffedCatch'] = pd.notnull(struct.get('isMuffedCatch'))
    struct['isNoPlay'] = (
        ' (no play)' in struct['detail'] and
        'penalty enforced in end zone' not in struct['detail']
        if struct.get('detail') else False)
    struct['isOnside'] = struct.get('isOnside') == 'onside'
    struct['isSack'] = pd.notnull(struct.get('sackYds'))
    struct['isSafety'] = (struct.get('isSafety') == ', safety' or
                          (struct.get('detail') and
                           'enforced in end zone, safety' in struct['detail']))
    struct['isTD'] = struct.get('isTD') == ', touchdown'
    struct['isTouchback'] = struct.get('isTouchback') == ', touchback'
    struct['oob'] = pd.notnull(struct.get('oob'))
    struct['passLoc'] = PASS_OPTS.get(struct.get('passLoc'), np.nan)
    if struct['isPass']:
        pyds = struct['passYds']
        struct['passYds'] = pyds if pd.notnull(pyds) else 0
    if struct.get('penalty'):
        struct['penalty'] = struct['penalty'].strip()
    else:
        struct['penalty'] = None
    struct['penDeclined'] = struct.get('penDeclined') == 'Declined'
    if struct['quarter'] == 'OT':
        struct['quarter'] = 5
    struct['rushDir'] = RUSH_OPTS.get(struct.get('rushDir'), np.nan)
    if struct['isRun']:
        ryds = struct['rushYds']
        struct['rushYds'] = ryds if pd.notnull(ryds) else 0
    year = struct.get('season', np.nan)
    #struct['timeoutTeam'] = sportsref.nfl.teams.team_ids(year).get(
    #    struct.get('timeoutTeam'), np.nan
    #)
    struct['twoPointSuccess'] = struct.get('twoPointSuccess') == 'succeeds'
    struct['xpGood'] = struct.get('xpGood') == 'good'

    # Third, ensure types are correct
    bool_vars = [
        'fgGood', 'isBlocked', 'isChallenge', 'isComplete', 'isFairCatch',
        'isFieldGoal', 'isKickoff', 'isKneel', 'isLateral', 'isNoPlay',
        'isPass', 'isPresnapPenalty', 'isPunt', 'isRun', 'isSack', 'isSafety',
        'isSpike', 'isTD', 'isTimeout', 'isTouchback', 'isTwoPoint', 'isXP',
        'isMuffedCatch', 'oob', 'penDeclined', 'twoPointSuccess', 'xpGood'
    ]
    int_vars = [
        'down', 'fgBlockRetYds', 'fgDist', 'fumbRecYdLine', 'fumbRetYds',
        'intRetYds', 'intYdLine', 'koRetYds', 'koYds', 'muffRetYds',
        'pbp_score_aw', 'pbp_score_hm', 'passYds', 'penYds', 'puntBlockRetYds',
        'puntRetYds', 'puntYds', 'quarter', 'rushYds', 'sackYds', 'timeoutNum',
        'ydLine', 'yds_to_go'
    ]
    float_vars = [
        'exp_pts_after', 'exp_pts_before', 'home_wp'
    ]
    string_vars = [
        'challenger', 'detail', 'fairCatcher', 'fgBlockRecoverer',
        'fgBlocker', 'fgKicker', 'fieldSide', 'fumbForcer',
        'fumbRecFieldSide', 'fumbRecoverer', 'fumbler', 'intFieldSide',
        'interceptor', 'kneelQB', 'koKicker', 'koReturner', 'muffRecoverer',
        'muffedBy', 'passLoc', 'passer', 'penOn', 'penalty',
        'puntBlockRecoverer', 'puntBlocker', 'puntReturner', 'punter',
        'qtr_time_remain', 'rushDir', 'rusher', 'sacker1', 'sacker2',
        'spikeQB', 'tackler1', 'tackler2', 'target', 'timeoutTeam',
        'xpKicker'
    ]
    for var in bool_vars:
        struct[var] = struct.get(var) is True
    for var in int_vars:
        try:
            struct[var] = int(struct.get(var))
        except (ValueError, TypeError):
            struct[var] = np.nan
    for var in float_vars:
        try:
            struct[var] = float(struct.get(var))
        except (ValueError, TypeError):
            struct[var] = np.nan
    for var in string_vars:
        if var not in struct or pd.isnull(struct[var]) or var == '':
            struct[var] = np.nan

    # Fourth, create new helper variables based on parsed variables
    # creating fieldSide and ydline from location
    if struct['isXP']:
        struct['fieldSide'] = struct['ydLine'] = np.nan
    else:
        fieldSide, ydline = _loc_to_features(struct.get('location'))
        struct['fieldSide'] = fieldSide
        struct['ydLine'] = ydline
    # creating secsElapsed (in entire game) from qtr_time_remain and quarter
    if pd.notnull(struct.get('qtr_time_remain')):
        qtr = struct['quarter']
        mins, secs = [int(t) for t in struct['qtr_time_remain'].split(':')]
        struct['secsElapsed'] = qtr * 900 - mins * 60 - secs
    # creating columns for turnovers
    struct['isInt'] = pd.notnull(struct.get('interceptor'))
    struct['isFumble'] = pd.notnull(struct.get('fumbler'))
    # create column for isPenalty
    struct['isPenalty'] = pd.notnull(struct.get('penalty'))
    # create columns for EPA
    struct['team_epa'] = struct['exp_pts_after'] - struct['exp_pts_before']
    struct['opp_epa'] = struct['exp_pts_before'] - struct['exp_pts_after']
    return pd.Series(struct)


def _loc_to_features(loc):
    """Converts a location string "{Half}, {YardLine}" into a tuple of those
    values, the second being an int.

    :l: The string from the play by play table representing location.
    :returns: A tuple that separates out the values, making them missing
    (np.nan) when necessary.

    """
    if loc:
        if isinstance(loc, str):
            loc = loc.strip()
            if ' ' in loc:
                r = loc.split()
                r[0] = r[0].lower()
                r[1] = int(r[1])
            else:
                r = (np.nan, int(loc))
        elif isinstance(loc, float):
            return (np.nan, 50)
    else:
        r = (np.nan, np.nan)
    return r
