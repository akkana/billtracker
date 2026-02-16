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
# Something that consists only of a single committee code
COMMPAT_ALL = COMMPAT + r'$'
DAYPAT = r'\[(\d+)\]'


def action_code_iter(actioncode):
    """Iterate over an action code, like
       HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
       Yield each (action, leg_day, location) one by one.
       If an action (e.g. the first one) doesn't start with [leg_day],
       return 0 for that day.
    """
    actioncode = actioncode.strip()

    # Filter out double dashes and spaces next to dashes
    actioncode = re.sub(r'\s*-\s*(-\s*)*', '-', actioncode)

    # Cases where - is part of a word rather than a separator:
    # DNP-CS/DP, PASSED/H (40-21), re-ref, re-referred, re-referred to
    # Change those to underscores.
    actioncode = actioncode.replace('DNP-CS/DP', 'DNP_CS/DP')
    actioncode = re.sub(r're-ref(\s*-*)*', 're_ref ', actioncode)
    actioncode = re.sub(r'\((\d+)-(\d+)\)', r'(\1_\2)', actioncode)

    # re.split keeps the separators if they're enclosed in ().
    # That helps detect [leg day].
    # But now that has to be cleaned up.
    splitparts = re.split(r'(-|\[)', actioncode)
    # print(splitparts)
    parts = []
    listiter = enumerate(splitparts)
    for i, part in listiter:
        part = part.strip()
        # print(i, part)
        if not part:
            continue
        if part == '-':
            continue

        if part == '[':
            # A new legislative day, '[2] otherstuff'
            try:
                part += next(listiter)[1]
                i += 1
            except IndexError:
                print("Unmatched [ in action code:", actioncode, file=sys.stderr)

        parts.append(part)
    # print("parts:", parts)

    # Now there's a mostly clean list of parts, like
    # ['SCC/SHPAC/SJC', 'SCC', 'germane', 'SHPAC ', '[5] DP', 'SJC']
    curloc = None
    curday = 0
    curaction = None
    listiter = enumerate(parts)
    for i, part in listiter:
        part = part.strip()
        # print("\npart (in action_code_iter):", part)
        curaction = None

        # Is there a legislative day indicator, in [] ?
        m = re.match(DAYPAT, part)
        if m:
            try:
                curday = int(m.group(1))
                part = part[len(m.group(0)):].strip()
                if not part:
                    continue
            except ValueError:
                print("Non-integer pattern in brackets!", part,
                      file=sys.stderr)

        # Is the next piece just a committee? in which case it's a new location,
        # so use it for this action and throw away the committee-only piece
        try:
            nextpart = parts[i+1]
            if re.match(COMMPAT_ALL, nextpart):
                curloc = nextpart
                # print("Committee change to", curloc)
                next(listiter)
        except IndexError:
            pass

        if re.match(COMMPAT_ALL, part):
            # print(part, "is just a committee, curaction is", curaction)
            # A special case: a committee repeated twice,
            # COMM-COMM, is a committee assignment similar
            # to the multiple committee COMMA/COMMB/COMMC structure.
            # We have no special syntax for that, so turn it into COMM/ COMM
            try:
                # print("next part: '%s'" % (parts[i+1]))
                if parts[i+1].strip() == part:
                    part += '/'
                    # print("Found %s%s" % (part, parts[i+1]))
            except IndexError:
                # print("committee pattern but couldn't get next part",
                #       parts[i:], "from", actioncode, file=sys.stderr)
                # That means we're ending with a committee.
                curloc = part
                yield(part, curday, curloc)
                continue

            if curaction:
                curloc = part
                yield curaction, curday, curloc
                continue
            elif part != curloc:
                curloc = part
                yield curloc, curday, curloc
                continue

        # If there isn't a curloc yet, use the first committee that starts a part.
        if not curloc:
            m = re.match(COMMPAT, part)
            if m:
                # print("Setting first curloc")
                curloc = m.group(0)

        curaction = None
        # print("*** yield", part, curday, curloc)
        # Undo the substitution from dashes to underscores
        yield part.replace('_', '-'), curday, curloc.replace('/', '')


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
    actioncode = actioncode.strip()

    legday = 0
    curloc = None
    history = []
    assigned = []

    # The history code is one long line, like
    # HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
    # 'HPREF [2] HGEIC/HTRC-HGEIC [3] DNP-CS/DP-HTRC [4] DNP-CS/DP  [6] PASSED/H (62-0)- STBTC/SJC-STBTC [13] DP-SJC [15] DP  [17] PASSED/S (39-0) SGND BY GOV (Mar. 20) Ch. 10.
    # Most actions start with [legislative day], but the committee that
    # caused the action comes before the [day], except in the case of
    # the first action.

    # There are problems with things like "w/o rec-HENRC"
    # which will be expected to be committee names because of the slash,
    # so first make a substitute for those.
    actioncode = actioncode.replace('/w/o rec/a-', ' no-rec -')
    actioncode = actioncode.replace('w/o rec/a-', ' no-rec -')
    actioncode = actioncode.replace('/w/o rec-', ' no-rec -')
    actioncode = actioncode.replace('w/o rec-', ' no-rec -')

    codeiter = action_code_iter(actioncode)
    for piece, legday, loc in codeiter:
        # print("from iterator: piece: '%s', legday: %s, loc: %s"
        #       % (piece, legday, loc))

        if not piece:
            # print("null piece!")
            continue
        piece = piece.strip()

        # If there was any form of Do Pass (DP) and it's in its last
        # assigned committee, move it to the chamber floor,
        # since that isn't shown in the action code like for committees.
        # But CAUTION: a bill can also be "DP - FAILED".
        # The iterator will hopefully weed those out.
        if 'DP' in piece and assigned and curloc == assigned[-1]:
            loc = curloc[0]

        if 'DP/a' in piece:
            history.append([ legday, "Do pass as amended by %s" % curloc,
                             piece, loc ])
            curloc = loc
            continue

        # Do Pass of a committee substitute
        m = re.search(r'DNP\s*CS\s*/\s*DP', piece)
        if m:
            history.append([ legday, "Do pass of committee sub by %s" % curloc,
                             piece, loc ])
            curloc = loc
            continue

        # A Do Pass without amendment
        m = re.search(r'\bDP\b', piece)
        if m:
            history.append([ legday, "Do pass by %s" % curloc, piece, loc ])
            curloc = loc
            continue

        # Other terms like german and no-rec:
        if piece == 'germane':
            curloc = loc
            history.append([ legday, "Ruled germane", piece, curloc ])
            continue

        if piece == 'no-rec':
            history.append([ legday, "No recommendation", piece, curloc ])
            continue

        # fl, fl/, fl/a+
        if piece.startswith('fl'):
            # There was a floor amendment, but that passage
            # isn't in this word, so pick up the next word
            floor_amendment = " with a floor amendment"
            piece = next(codeiter)[0].strip()
        else:
            floor_amendment = ""

        # Passing the House or Senate, possibly with (for-against) appended
        m = re.search(r'PASSED/([HS])(\s*\(\d+-\d+\))*', piece)
        if m:
            chamber = m.group(1)
            if chamber == 'H':
                chambername = 'House'
                curloc = 'H'
            elif chamber == 'S':
                chambername = 'Senate'
                curloc = 'S'
            else:
                print("**** Error PASSED", chamber,
                      "which is not H or S", piece,
                      file=sys.stderr)
                curloc = None
                continue
            # group 2 is votes, e.g. "Passed House (44-23)"
            # but it's often missing
            if m.group(2):
                history.append([ legday,
                                 "Passed %s%s%s" % (chambername, m.group(2),
                                                    floor_amendment),
                                 piece, curloc ])
            else:
                history.append([ legday, "Passed %s%s" % (chambername,
                                                          floor_amendment),
                                 piece, curloc ])
            continue

        if piece.startswith('SGND'):
            curloc = 'SIGNED'
            history.append([ legday, "Signed by Governor", piece, curloc ])
            # It's actually 'SGND BY GOV' but just ignore the other 2 words,
            # it's not like it can be SGND by anyone else.
            continue

        # Withdrawn, which has a slash that could be confused
        # with committee assignment.
        # This could have other things in it, e.g. 'w/drn h/calendar'
        # I don't know what h/calendar means and it's not on the
        # nmlegis abbreviations page.
        if 'w/drn' in piece:
            curloc = loc
            history.append([ legday, "Withdrawn", piece, loc ])
            continue

        if 'FAILED' in piece:
            history.append([ legday, piece, piece, loc ])
            continue

        # re-ref, re-referred, re-referred to etc.
        if piece.startswith('re-ref'):
            # pick out the committee name
            comm = re.search(r'\b' + COMMPAT + r'$', piece)
            if comm:
                history.append([ legday, "Re-referred to %s" % comm.group(0),
                                 piece, comm.group(0) ])
            else:
                # re-ref but couldn't find a committee code
                print("Couldn't find a committee code in", piece,
                      "-- from '%s'" % actioncode, file=sys.stderr)
                history.append([ legday, piece, piece, curloc ])
            continue

        # Multiple committee assignment. Python re isn't smart enough
        # to do this with pure regex, as far as I can tell.
        # Note that in the case of a single committee assignment,
        # the iterator sends COMMCODE/ so the second committee will be blank.
        if '/' in piece:
            # I think "ref " preceding a comm/comm/comm assignment
            # is a no-op, the ref part doesn't mean anything.
            if piece.startswith('ref '):
                piece = piece[4:]
            assigned = [ c.strip() for c in piece.split('/') ]
            assigned = [ c for c in assigned if c ]    # Weed out nulls
            for c in assigned:
                # rec will occur because of strings like '[4] w/o rec-SFC'
                # so it only applies in the context of nearby words.
                if c == 'rec':
                    break   # there won't be any more committees
                if not re.match(COMMPAT, c):
                    print("Seeming committee assignment but",
                          "'%s' doesn't match committee pattern:" % c,
                          piece, file=sys.stderr)
                    raise ValueError
            curloc = assigned[0]
            history.append([ legday, "Assigned %s" % '/'.join(assigned),
                             piece, curloc ])
            if curloc not in assigned:
                print("Parse problem:", curloc,
                      "is not in commmittee list", assigned,
                      "in", piece, file=sys.stderr)

                # Treat it as a loc anyway
                curloc = loc
                history.append([ legday, "Now in %s" % curloc, piece, curloc ])
            continue

        # Not printed
        if r'not prntd' in piece:
            history.append([ legday, "Not printed", piece, curloc ])
            continue

        elif 'prntd' in piece:
            history.append([ legday, "Printed", piece, curloc ])
            continue

        # Single committee.
        m = re.match(COMMPAT, piece)
        if m and m.group(0) != curloc:
            curloc = m.group(0)
            # history.append([ legday, "Assigned %s" % curloc, piece, loc ])
            history.append([ legday, "Sent to %s" % curloc, piece, curloc ])
            continue

        # Passed current committee, nothing else
        if piece == 'DP/a':
            history.append([ legday, "Do pass as amended", piece, curloc ])
            continue
        if piece == 'DP':
            history.append([ legday, "Do pass", piece, curloc ])
            continue

        # Signed by the Governor; I don't think the legday is relevant
        if piece.startswith('SGND BY GOV'):
            curloc = "Signed"
            history.append([ 0, "Signed by Governor", piece, curloc ])

        # Passing to the next committee, with anything else not understood
        if loc != curloc:
            curloc = loc
            history.append([ legday, loc, piece, loc ])
            continue

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
    futurelocs = []

    # from pprint import pprint
    # print(billno, "history:")
    # pprint(history)

    # First get all the locations where it's actually been.
    for day, action, code, loc in history:
        if loc and loc not in pastlocs:
            pastlocs.append(loc)
            continue

    # The current location (the last loc setting)
    # is considered a future loc, not past, so move it,
    # unless it's SIGNED or CHAPTERED.
    if pastlocs:
        lastloc = pastlocs[-1]
        if lastloc != 'SIGNED' and lastloc != 'CHAPTERED':
            futurelocs.append(pastlocs.pop(-1))

    # Now store any assignments not in that list
    for day, action, code, loc in history:
        if action.startswith("Assigned "):
            assignments = action[9:].split('/')  # committee list
            for comm in assignments:
                if comm not in pastlocs and comm not in futurelocs:
                    futurelocs.append(comm)

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

    # Has it ever had any committees assigned?
    if not pastlocs and not futurelocs:
        futurelocs.append(starting_chamber + '???')

    # Has it been on its home chamber's floor yet?
    if starting_chamber not in pastlocs:
        futurelocs.append(starting_chamber)

    # Does it not yet have committees from the other chamber?
    # Note: non-joint memorials don't need to go through the other chamber.
    if (billno[1] != 'M' or billno[2] == 'J'
        and billno[1] != 'R' and billno[1:3] != 'CR'):
        # find the last committee assigned
        if futurelocs:
            lastcomm = futurelocs[-1]
        else:
            lastcomm = pastlocs[-1]
        if lastcomm[0] != other_chamber and lastcomm != 'SIGNED':
            futurelocs.append(other_chamber + '???')
        if other_chamber not in pastlocs and other_chamber not in futurelocs:
            futurelocs.append(other_chamber)

    # Hopefully that covers the chambers (though not details like
    # going back to the first chamber for concurrence with amendments).
    # Add the final step, which is the Governor.
    # Resolutions and memorials don't need any action from the Governor.
    if billno[1] != 'R' and billno[1] != 'M' and billno[1] != 'J' \
       and 'SIGNED' not in pastlocs and 'SIGNED' not in futurelocs:
            futurelocs.append('SIGNED')

    return pastlocs, futurelocs

if __name__ == '__main__':
    import sys
    # from pprint import pprint

    def print_hist_info(actioncode):
        location, status, histlist = decode_full_history(actioncode)
        print("Status:", status)
        # print("Last Action:", lastaction)
        print("History:")
        for day, longaction, code, location in histlist:
            print(f"  Day {day}: {longaction} (now in {location}) ('{code}')")

        pastloc, futureloc = get_location_lists("SB001", histlist)
        print("Past locations:", ' '.join(pastloc))
        print("Future locations:", ' '.join(futureloc))

    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            print_hist_info(arg)
        sys.exit(0)


