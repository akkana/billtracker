#!/usr/bin/env python3

"""Handle status/location codes used on nmlegis.org
"""

import re

# Locations that are not committees
special_locations = ( "Senate", "House", "Passed", "Died",
                      "Chaptered", "Signed", "Not Printed",
                      "Senate Pre-file", "House Pre-file"
                    )

def is_special_location(loc):
    """Is loc a location other than a committee, e.g. "Senate", "Passed"?
    """
    for special in special_locations:
        if loc.startswith(special):
            return True
    return False


def action_code_iter(actioncode):
    """Iterate over an action code, like
       HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
       Yield each (action, leg_day) one by one.
       If an action (e.g. the first one) doesn't start with [leg_day],
       return 0 for that day.
    """
    idx = 0    # position so far
    actioncode = actioncode.lstrip()
    while actioncode:
        if actioncode.startswith('['):
            actioncode = actioncode[1:]
            closebracket = actioncode.find(']')
            if closebracket < 0:
                # print("Syntax error, no closebracket")
                # Syntax error, yield everything left in the string.
                leg_day = 0
                action = actioncode
                actioncode = None
                yield action, leg_day
                continue
            # Whew, there is a closebracket
            leg_day = actioncode[:closebracket].strip()
            actioncode = actioncode[closebracket+1:].lstrip()
        else:
            leg_day = 0
        # Now we either have leg_day or not. Find the first action.
        nextbracket = actioncode.find('[')
        if nextbracket >= 0:
            action = actioncode[:nextbracket].rstrip()
            actioncode = actioncode[nextbracket:]
            yield action, leg_day
            continue
        # No next bracket, this is the last action.
        action = actioncode
        actioncode = ''
        yield action, leg_day


# The raw abbreviations dict
# from https://www.nmlegis.gov/Legislation/Action_Abbreviations
abbreviations = {
   '\*': 'Emergency clause',
   'API.': 'Action postponed indefinitely',
   'CC': 'Conference committee (Senate and House fail to agree)',
   'CS': 'Committee substitute',
   # 'CS/H 18': 'Committee substitute for House Bill 18.',
   'DEAD': 'Bill Has Died',
   'DNP nt adptd': 'Do Not Pass, committee report NOT adopted',
   'DNP': 'Do Not Pass, committee report adopted',
   'DP/a': 'Do Pass, as amended, committee report adopted.',
   'DP': 'Do Pass committee report adopted.',
   'E&E': 'The final authoritative version of a bill passed by both houses of the legislature',
   'FAILED/H': 'Failed passage in House',
   'FAILED/S': 'Failed passage in Senate',
   'fl/a': 'Floor amendment adopted. (fl/aaa - three floor amendments adopted.)',
   'FL/': 'Floor substitute',
   'germane': 'Bills which fall within the purview of a 30-day session.',
   'h/cncrd': 'House has concurred in Senate amendments on a House bill',
   'h/fld cncr': 'House has failed to concur in Senate amendments on a House bill. The House then sends a message requesting the Senate to recede from its amendments.',
   'HCAL': 'House Calendar',
   'HCAT': 'House Temporary Calendar',
   'HCNR': 'House Concurrence Calendar',
   'HCW': 'Committee of the Whole',
   'HINT': 'House Intro',
   'HPREF': 'House Pre-file',
   'HPSC': 'Printing & Supplies',
   'HTBL': 'House Table',
   'HXPSC': 'House Printing & Supplies Committee',
   'HXRC': 'HOUSE RULES & ORDER OF BUSINESS',
   'HZLM': 'In Limbo (House)',
   'm/rcnsr adptd': 'Motion to reconsider previous action adopted.',
   'OCER': 'Certificate',
   'PASSED/H': 'Passed House',
   'PASSED/S': 'Passed Senate',
    # 'PASS': 'Passed',
   'PCA': 'Constitutional Amendment',
   'CA': 'Constitutional Amendment',
   'PCH': 'Chaptered',
   'PKVT': 'Pocket Veto',
   'PSGN': 'Signed',
   'PVET': 'Vetoed',
   'QSUB': 'Substituted',
   'rcld frm/h': 'Bill recalled from the House for further consideration by the Senate',
   'rcld frm/s': 'Bill recalled from the Senate for further consideration by the House.',
   's/cncrd': 'Senate has concurred in House amendments on a Senate bill',
   's/fld recede': 'Senate refuses to recede from its amendments',
   'SCAL': 'Senate Calendar',
   'SCC': 'Committees’ Committee',
   'SCNR': 'Senate Concurrence Calendar',
   # 'SCS/H 18': 'Senate committee substitute for House Bill 18. (CS, preceded by the initial of the opposite house, indicates a substitute for a bill made by the other house. The listing, however, will continue under the original bill entry.)',
   'SCs': 'Senate Committee Substitute',
   'SCW': 'Committee of the Whole',
   # 'SGND(C.A.2).': 'Constitutional amendment and its number.',
   # 'SGND(Mar.4)Ch.9.': 'Signed by the Governor, date and chapter number.',
   'SGND': 'Signed by one or both houses (does not require Governor’s signature)',
   'SINT': 'Senate Intro',
   'SPREF': 'Senate Pre-file',
   'STBL': 'Senate Table',
   'SZLM': 'In Limbo (Senate)',
    'T': 'On the Speaker’s table by rule (temporary calendar)',
   'tbld': 'Tabled temporarily by motion.',
   'TBLD INDEF.': 'Tabled indefinitely.',
   'VETO(Mar.7).': 'Vetoed by the Governor and date.',
   'w/drn': 'Withdrawn from committee or daily calendar for subsequent action.',
   'w/o rec': 'WITHOUT RECOMMENDATION committee report adopted.',
}

# A list of compiled regexps from the abbreviations list,
# with word boundaries around them.
# This is needed because, for example, T is an abbreviation
# for 'On the Speaker’s table' but we can't just replace every T,
# there are committees (and expansions of other abbreviations)
# that include T.
# And using \b as the word delimiter doesn't work, because - might
# come after T but re considers - to be part of a word.
abbrev_re = [ (re.compile(r'\b%s\b' % key), abbreviations[key])
              for key in abbreviations.keys() ]


def decode_full_history(actioncode):
    """Decode a bill's full history according to the code specified in
       https://www.nmlegis.gov/Legislation/Action_Abbreviations
       Returns location, status (action string), histlist
         where histlist is a list of (day, actionstring, actioncode, location)
         tuples.
    """
    # The history code is one long line, like
    # HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
    # Most actions start with [legislative day] but the first may not.
    histlist = []
    for action, legday in action_code_iter(actioncode):
        actionstring, location = decode_history_day(action, legday)
        histlist.append((int(legday), actionstring, action, location))
    lasttuple = histlist[-1]
    lastaction = "Legislative Day %s: %s" % (lasttuple[0], lasttuple[1])
    # location and actionstring(=status) are taken from the last history item.

    # print("  Location:", location, file=sys.stderr)
    # print("  actionstring:", actionstring, file=sys.stderr)
    # print("  lastaction:", lastaction, file=sys.stderr)
    # print("  histlist:", histlist, file=sys.stderr)
    return location, lastaction, histlist


def full_history_text(actioncode):
    """Return a newline-separated string of actions for a bill"""
    return '\n'.join([ "%d: %s" % (l[0], l[1])
                       for l in decode_full_history(actioncode)[-1] ])


comchange_pat = re.compile('([a-zA-Z]{3,})/([a-zA-Z]{3,})-([a-zA-Z]{3,})')
end_comcode_pat = re.compile('-([A-Z]{3,})$')


def decode_history_day(actioncode, legday):
    """Decode a single history day according to the code specified in
       https://www.nmlegis.gov/Legislation/Action_Abbreviations
       For instance, 'HCPAC/HJC-HCPAC' -> 'Moved to HCPAC, ref HJC-HCPAC'
       Returns actionstring, location
       where actionstring tries to be a human-readable string,
       and location is our best guess at where the bill is now.
    """
    location = None

    # If the full day's description ends with -COMCODE,
    # that committee is the new location.
    m = end_comcode_pat.search(actioncode)
    if m:
        location = m.group(1)
        actioncode = actioncode[:m.span()[0]] + " Sent to " + location

    # Committee changes are listed as NEWCOMM/COMM{,-COMM}
    # where the comms after the slash may be the old committee,
    # the new committee or some other committee entirely.
    # The abbreviations page doesn't explain.
    # However, slashes can also mean other things, e.g.
    #   CS/H 18, DP/a, FAILED/H or S, FL/, fl/aaa, h/fld cncr,
    #   m/rcnsr adptd, rcld frm/h, s/cncrd, s/fld, SCS/H 18, w/drn, w/o rec
    # It seems like committee movements will always have at least three
    # alphabetic characters on either side of the slash.
    # And it should end with -COMCODE with the code of the current committee.
    match = re.search(comchange_pat, actioncode)
    if match:
        return ('Sent to %s, ref %s' % (match.group(1), match.group(2)),
                match.group(3))

    # It's not a committee assignment; decode what we can.
    # It's not obvious how to get location, so just take the
    # whole decoded last action.
    actionstr = actioncode
    for pat, expanded in abbrev_re:
        actionstr = pat.sub(expanded, actionstr)
    return (actionstr, location)


if __name__ == '__main__':
    import sys
    for arg in sys.argv[1:]:
        location, status, lastaction, histlist = decode_full_history(arg)
        print()
        print("===", arg)
        print("Location:", location)
        print("Status:", status)
        print("Last Action:", lastaction)
        for day, longaction, code in histlist:
            print("  ", day, ":", code, "->", longaction)

