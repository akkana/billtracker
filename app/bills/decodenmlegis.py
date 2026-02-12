#!/usr/bin/env python3

"""Handle status/location codes used on nmlegis.org
"""

import re
import sys

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
   r'\*': 'Emergency clause',
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


# A pattern matching committee codes
COMMPAT = r'[HS][A-Z]{2,5}'


def full_history_text(fullhist):
    """Given a full history for a bill,
       return a newline-separated string of actions.
    """
    histstr = ''
    legday = None
    for day, actionstring, actioncode, location in fullhist:
        if day != legday:
            if histstr:
                histstr += '\n'
            legday = day
            histstr += "Legislative day %s:\n    " % day
        elif legday:
            # appending another item to a legislative day
            histstr += '\n    '
        histstr += actionstring

    return histstr


def decode_full_history(actioncode):
    """Decode a bill's full history according to the code specified in
       https://www.nmlegis.gov/Legislation/Action_Abbreviations
       Returns current_location, status (action string), histlist
         where histlist is a list of (day, actionstring, actioncode, location)
         tuples.
    """
    legday = 0
    curloc = None
    history = []

    # The history code is one long line, like
    # HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
    # 'HPREF [2] HGEIC/HTRC-HGEIC [3] DNP-CS/DP-HTRC [4] DNP-CS/DP  [6] PASSED/H (62-0)- STBTC/SJC-STBTC [13] DP-SJC [15] DP  [17] PASSED/S (39-0) SGND BY GOV (Mar. 20) Ch. 10.
    # Most actions start with [legislative day] but the first may not.
    # First try: can we split by whitespace?
    # It mostly works, but there are problems with things like "w/o rec-HENRC"
    # which will be expected to be committee names because of the slash,
    # so first make a substitute for those.
    actioncode = actioncode.replace('/w/o rec/a-', ' no-rec -')
    actioncode = actioncode.replace('w/o rec/a-', ' no-rec -')
    actioncode = actioncode.replace('/w/o rec-', ' no-rec -')
    actioncode = actioncode.replace('w/o rec-', ' no-rec -')

    for piece in actioncode.split():
        # Is it a new legislative day?
        try:
            m = re.match(r'\[([0-9]+)\]', piece)
            legday = int(m.group(1))
            continue
        except AttributeError:
            # not a legislative day
            pass

        # A Do Pass as amended, plus referral to the next committee
        m = re.search(f'DP/a-({COMMPAT})', piece)
        if m:
            history.append([ legday, "Do pass as amended by %s" % curloc,
                             piece, curloc ])
            curloc = m.group(1)
            history.append([ legday, "Sent to %s" % curloc, piece, curloc ])
            continue

        # Do Pass of a committee substitute, plus referral to the next committee
        m = re.search(f'DNP-CS/DP-({COMMPAT})', piece)
        if m:
            history.append([ legday, "Committee sub do pass by %s" % curloc,
                             piece, curloc ])
            curloc = m.group(1)
            history.append([ legday, "Sent to %s" % m.group(1), piece, curloc ])
            continue

        # A Do Pass without amendment, plus referral to the next committee
        m = re.search(f'DP-({COMMPAT})', piece)
        if m:
            history.append([ legday, "Do pass by %s" % curloc, piece, curloc ])
            curloc = m.group(1)
            history.append([ legday, "Sent to %s" % m.group(1), piece, curloc ])
            continue

        # But a DP can be on its own too, especially if its next step
        # is the House or Senate
        m = re.search(r'\bDP\b', piece)
        if m:
            history.append([ legday, "Do pass by %s" % curloc, piece, curloc ])
            continue

        # Pick out those no-recs that were substituted earlier:
        if piece == 'no-rec':
            history.append([ legday, "No recommendation", piece, curloc ])

        # Passing the House or Senate
        m = re.search(r'PASSED/([HS])', piece)
        if m:
            chamber = m.group(1)
            if chamber == 'H':
                chambername = 'House'
                curloc = 'S'
            elif chamber == 'S':
                chambername = 'Senate'
                curloc = 'H'
            else:
                print("**** Error PASSED", chamber,
                      "which is not H or S", piece,
                      file=sys.stderr)
                curloc = None
            history.append([ legday, "Passed %s" % chambername,
                              piece, curloc ])
            continue

        if piece == 'SGND':
            history.append([ legday, "Signed by Governor",
                              piece, curloc ])
            # It's actually 'SGND BY GOV' but just ignore the other 2 words,
            # it's not like it can be SGND by anyone else.
            continue

        # Withdrawn, which has a slash that could be confused
        # with committee assignment
        m = re.search(f'w/drn-({COMMPAT})', piece)
        if m:
            history.append([ legday, "Withdrawn", piece, curloc ])
            curloc = m.group(1)
            history.append([ legday, "Sent to %s" % curloc, piece, curloc ])
            continue

        # fl, fl/, fl/a
        if piece.startswith('fl'):
            # There was an amendment on a chamber floor, but that passage
            # isn't in this word, so just ignore it.
            continue

        # # Single committee assignment, which looks like SJC-SJC
        # m = re.match(f'({COMMPAT})-({COMMPAT})', piece)
        # if m and m.group(1) == m.group(2):
        #     curloc = m.group(1)
        #     history.append([ legday, "Assigned %s" % curloc,
        #                          piece, curloc ])

        # Multiple committee assignment. Python re isn't smart enough
        # to do this with pure regex, alas.
        try:
            if ('/' in piece and '-' in piece and
                piece.rfind('/') < piece.rfind('-')):
                assignments, loc = piece.split('-')
                committees = [ c.strip() for c in assignments.split('/') ]
                for c in committees:
                    # rec will occur because of strings like '[4] w/o rec-SFC'
                    # so it only applies in the context of nearby words.
                    if c == 'rec':
                        break   # there won't be any more committees
                    if not re.match(COMMPAT, c):
                        print("**** seeming committee assignment but",
                              "'%s' doesn't match committee pattern:" % c,
                              piece, file=sys.stderr)
                        raise ValueError
                history.append([ legday, "Assigned %s" % assignments,
                                 piece, curloc ])
                if loc not in committees:
                    print("****** Parse problem: loc", loc,
                          "is not in commmittee list", committees,
                          "in", piece, file=sys.stderr)
                # Treat it as a loc anyway
                curloc = loc
                history.append([ legday, "Sent to %s" % curloc, piece, curloc ])
                continue
        except ValueError:
            continue

        # Not printed, but assigned
        m = re.match(f'prntd-({COMMPAT})', piece)
        if m:
            curloc = m.group(1)
            history.append([ legday, "Not printed, sent to %s" % curloc,
                             piece, curloc ])
            continue

        # Only assigned one committee, dash but no slashes, e.g. SJC-SJC
        m = re.match(f'({COMMPAT})-({COMMPAT})', piece)
        if m:
            if m.group(1) != m.group(2):
                print("**** expected these two to be equal:",
                      m.group(1), m.group(2), file=sys.stderr)
            # Use just the second one
            curloc = m.group(2)
            history.append([ legday, "Assigned %s" % curloc, piece, curloc ])
            history.append([ legday, "Sent to %s" % curloc, piece, curloc ])
            continue

        # Passed current committee, nothing else
        if piece == 'DP/a':
            history.append([ legday, "Do pass as amended", piece, curloc ])
            continue
        if piece == 'DP':
            history.append([ legday, "Do pass", piece, curloc ])
            continue

        # Passing to the next committee, with anything else not understood
        m = re.search(f'-({COMMPAT})', piece)
        if m:
            curloc = m.group(1)
            history.append([ legday, "Sent to %s" % curloc, piece, curloc ])
            continue

        # Signed by the Governor; I don't think the legday is relevant
        if piece.startswith('SGND BY GOV'):
            curloc = "Signed"
            history.append([ 0, "Signed by Governor", piece, curloc ])

    return curloc, actioncode, history


def get_location_lists(billno, history):
    """Get the list of locations a bill has already passed,
       and what we know about future locations.
       history can be either a decoded full history,
       or a status code to pass to decode_full_history().
    """
    if type(history) is str:
        location, status, history = decode_full_history(history)

    pastlocs = []
    assignments = []
    curloc = None
    # print(billno, "history:")
    for day, action, code, loc in history:
        if action.startswith("Assigned "):
            assignments = action[9:].split('/')  # committee list
        elif action.startswith('Do pass'):
            if curloc:
                pastlocs.append(curloc)
                try:
                    assignments.remove(curloc)
                except ValueError:
                    print(billno, "curloc", curloc, "wasn't in assignments",
                          assignments) # , file=sys.stderr)
            curloc = None
        elif action.startswith('Passed '):
            pastlocs.append(action[7])
            assignments = []
            curloc = None
        elif action.startswith("Sent to"):
            if curloc:
                pastlocs.append(curloc)
            curloc = loc
        elif action.startswith("Signed"):
            curloc = None
            pastlocs.append('SIGNED')

            # that's as far as a bill can go, so it's safe to return now
            return pastlocs, []

    futurelocs = []
    if curloc:
        futurelocs.append(curloc)
    if assignments:
        futurelocs += assignments

    # Now figure out what's missing, what hasn't been assigned yet,
    # ending with the Governor.
    # First figure out which chamber it started in:
    if pastlocs:
        starting_chamber = pastlocs[0][0]
    else:
        # It's presumably starting in the same chamber as its billno
        starting_chamber = billno[0]

    if futurelocs:
        last_chamber = futurelocs[-1][0]
    elif pastlocs:
        last_chamber = pastlocs[-1][0]
    else:
        last_chamber = starting_chamber

    if starting_chamber == 'S':
        other_chamber = 'H'
    else:
        other_chamber = 'S'

    # Has it ever had committees assigned?
    if not pastlocs and not futurelocs:
        futurelocs.append(starting_chamber + '???')

    # Has it been on its home chamber's floor yet?
    if starting_chamber not in pastlocs:
        futurelocs.append(starting_chamber)

    # Does it not yet have committees from the other chamber?
    # Note: non-joint memorials don't need to go through the other chamber.
    if billno[1] != 'M' and billno[1] != 'R' and billno[1:3] != 'CR':
        if last_chamber == starting_chamber:
            futurelocs.append(other_chamber + '???')
            futurelocs.append(other_chamber)
        elif other_chamber not in pastlocs:
            # it has committees but not the floor session
            futurelocs.append(other_chamber)

    # Hopefully that covers the chambers (though not details like
    # going back to the first chamber for concurrence with amendments).
    # Add the final step, which is the Governor.
    # Resolutions and memorials don't need any action from the Governor.
    if billno[1] != 'R' and billno[1] != 'M' and billno[1] != 'J':
        futurelocs.append('SIGNED')

    return pastlocs, futurelocs


if __name__ == '__main__':
    import sys
    # from pprint import pprint

    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            location, status, histlist = decode_full_history(arg)
            print("Status:", status)
            # print("Last Action:", lastaction)
            print("History:")
            for day, longaction, code, location in histlist:
                print(f"  Day {day}: {longaction}, now in {location} ({code})")
        sys.exit(0)

    import json
    fp = open('tests/files/billstatuses.json')
    allbills = json.load(fp)
    for billno in allbills:
        print()
        print("\n===", billno)

        location, status, histlist = decode_full_history(allbills[billno])
        # print()
        # pprint(histlist)
        print("Location:", location)
        print("Status:", status)
        # print("Last Action:", lastaction)
        print("History:")
        for day, longaction, code, location in histlist:
            print(f"  Day {day}: {longaction}, now in {location} ({code})")

        # Get just locations, assuming any location change indicates a pass.
        pastloc, futureloc = get_location_lists(billno, histlist)
        print("Past locations:", ' '.join(pastloc))
        print("Future locations:", ' '.join(futureloc))

