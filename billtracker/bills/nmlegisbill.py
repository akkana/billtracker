#!/usr/bin/env python3

from __future__ import print_function

from .billutils import year_to_2digit, billno_to_parts, URLmapper
from . import billrequests

# Scrape bill data from bill pages from nmlegis.org.

import sys, os
import datetime, dateutil.parser
import time
import re
import posixpath
from collections import OrderedDict
from bs4 import BeautifulSoup
import json
import xlrd
import traceback

# XXX Requests is only needed temporarily while introducing Ed's PDF
# calendar parser. Eventually we should get that via billrequests
# like everything else.
import requests

# A bill pattern, allowing for any number of extra leading zeros
# like the FIR/LESC links randomly add.
# If there are other letters or a different pattern,
# it may be an amendment or some other supporting document.
billno_pat = re.compile("([SH][JC]{0,1}[BMR])(0*)([1-9][0-9]*)")

# Same thing, but occurring in a file pathname,
# so it should start with / and end with .
bill_file_pat = re.compile(".*/([SH][JC]{0,1}[BMR])(0*)([1-9][0-9]*)\.")


# XXX The URLmapper stuff should be killed, with any functionality
# that's still needed moved into billrequests.
url_mapper = URLmapper('https://www.nmlegis.gov',
    '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')


def yearcode_to_longURLcode(yearcode):
    """Map a short yearcode like "20s2" to a long URL code used for
       the analysis pages, like "".
    """
    # The 2-digit year part
    year2 = yearcode[:2]

    if yearcode.endswith('s') or yearcode.endswith('s1'):
        return year2 + '%20Special'

    if yearcode.endswith('s2'):
        return year2 + '%20Special2'

    if yearcode.endswith('s3'):
        return year2 + '%20Special3'

    if yearcode.endswith('x'):
        return year2 + '%20Extraordinary'

    return year2 + '%20Regular'


def bill_url(billno, yearcode):
    chamber, billtype, number = billno_to_parts(billno)

    return 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' % (chamber, billtype, number, yearcode)


scheduled_for_pat = re.compile("Scheduled for.*on ([0-9/]*)")
sponcode_pat = re.compile(".*[&?]SponCode\=([A-Z]+)")


def parse_bill_page(billno, yearcode, cache_locally=True, cachesecs=2*60*60):
    """Download and parse a bill's page on nmlegis.org.
       Yearcode is the session code, like 19 or 20s2.
       Return a dictionary containing:
       chamber, billtype, number, year, title,
       sponsor, sponsorlink, location.
       The year is really a yearcode, but needs to match the Bill
       object's set_from_parsed_page so we call it just year.
       Set update_date to now.

       If cache_locally, will save downloaded files to local cache.
       Will try to read back from cache if the cache file isn't more
       than 2 hours old.

       Does *not* save the fetched bill back to the database.
    """
    billdic = { 'billno': billno }
    (billdic['chamber'], billdic['billtype'], billdic['number']) \
        = billno_to_parts(billno)
    billdic['year'] = yearcode

    baseurl = 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' \
        % (billdic['chamber'], billdic['billtype'],
           billdic['number'], billdic['year'])

    soup = billrequests.soup_from_cache_or_net(baseurl, billdic,
                                               cachesecs=cachesecs)

    # If something failed -- for instance, if we got an empty file
    # or an error page -- then the title span won't be there.
    # Detect that:
    try:
        billdic['title'] = soup.find("span",
            id="MainContent_formViewLegislation_lblTitle").text
    except AttributeError:
        print(billno, "Couldn't find title span", file=sys.stderr)
        return None

    sponsor_a = soup.find("a",
                          id="MainContent_formViewLegislation_linkSponsor")
    billdic['sponsorlink'] = url_mapper.to_abs_link(sponsor_a.get('href'),
                                                    baseurl)
    m = sponcode_pat.match(billdic['sponsorlink'])
    if (m):
        billdic['sponsor'] = m.group(1)

        # The rest of the sponsors have link IDs like
        # MainContent_formViewLegislation_linkSponsor2, etc.
        # so loop over those until there are no more.
        i = 2
        while True:
            sponsor_a = soup.find(
                "a", id="MainContent_formViewLegislation_linkSponsor%d" % i)
            if not sponsor_a:
                break
            sponsor_a = sponsor_a.get('href')
            if not sponsor_a:
                break
            m = sponcode_pat.match(sponsor_a)
            if m:
                billdic['sponsor'] += "," + m.group(1)
            i += 1

    else:
        print("ERROR: No sponcode in", billdic['sponsorlink'], file=sys.stderr)
        billdic['sponsor'] = sponsor_a.text.strip()

    curloc_a  = soup.find("a",
                          id="MainContent_formViewLegislation_linkLocation")
    curloc_href = curloc_a.get('href')
    curloc_text = curloc_a.text.strip()
    if curloc_href:
        # could be https://www.nmlegis.gov/Entity/House/Floor_Calendar
        # or https://www.nmlegis.gov/Committee/Standing_Committee?CommitteeCode=HHHC
        match = re.search('CommitteeCode=([A-Za-z]*)', curloc_href)
        if match:
            billdic['curloc'] = match.group(1)
        elif 'Floor_Calendar' in curloc_href:
            if '/House/' in curloc_href:
                billdic['curloc'] = 'House'
            else:
                billdic['curloc'] = 'Senate'

        # In 2020, they've started adding "Scheduled for" to the
        # curloc text if the bill is scheduled (sometimes).
        # Sometimes that's the only clue to scheduling, so look for it,
        # though it typically has only the date, not the time.
        # If it's not here, it might get filled in when the committee
        # gets updated.
        scheduled_for = scheduled_for_pat.match(curloc_text)
        if scheduled_for:
            schedstr = scheduled_for.group(1)
            try:
                billdic['scheduled_date'] = dateutil.parser.parse(schedstr)
            except:
                print("Couldn't parse scheduled date", schedstr,
                      "from '%s'" % curloc_text)

    # XXX What's the code for On Governor's Desk? Or Failed, or others?
    # XXX There's also a case where curloc_a is blank and curloc will
    # be something like "<b>Senate Intro</b> except with a lot of blanks
    # and newlines inside. Currently those show up as 'unknown':
    # I need to catch one in the act to test code to handle it,
    # and they don't stay in that state for long.

    # Bills seem to have a text of "Chaptered", with no href,
    # once they're signed. There are probably other special vals too.
    else:
        billdic['curloc'] = curloc_text

    contents_a = soup.find("a",
                           id="MainContent_formViewLegislationTextIntroduced_linkLegislationTextIntroducedHTML")
    if contents_a:
        billdic['contentslink'] = url_mapper.to_abs_link(contents_a.get('href'),
                                                         baseurl)

    # Does the bill have any amendments?
    # Unfortunately we can't get the amendments themselves --
    # they're only available in PDF. But we can see if they exist.
    amendbutton = soup.find("a", id="MainContent_formViewAmendmentsInContext_linkAmendmentsInContext")
    if amendbutton:
        billdic["amendlink"] = url_mapper.to_abs_link(amendbutton.get('href'),
                                                      baseurl)

    # The amendments link in the button is just the "Amendments_In_Context" PDF.
    # But if that's not there, there may be other types of amendments,
    # like committee substitutions.
    # This might be supplemented or overwritten later by api/refresh_legisdata.
    if "amendlink" not in billdic or not billdic["amendlink"]:
        cspat = re.compile("MainContent_dataListLegislationCommitteeSubstitutes_linkSubstitute.*")
        cslink = soup.find("a", id=cspat)
        if cslink:
            billdic['amendlink'] = url_mapper.to_abs_link(cslink.get('href'),
                                                          baseurl)
            # Usually this is a PDF but there's a .html
            # in the same directory. See if there is:
            if billdic['amendlink'].endswith('.pdf'):
                html_cs = re.sub('.pdf', '.html', billdic['amendlink'])
                if billrequests.head(html_cs).status_code == 200:
                    billdic['amendlink'] = html_cs

    # Bills have an obscure but useful actiontext code, e.g.
    # HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
    # which could be decoded to show the bill's entire history.
    # Capture that as the last line of the actiontext.
    # XXX Eventually, make it a separate item in the database.
    actioncode = soup.find(id='MainContent_tabContainerLegislation_tabPanelActions_formViewActionText_lblActionText').text

    # The all-important part: what was the most recent action?
    actiontable = soup.find("table",
      id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions")

    actions = actiontable.findAll('span', class_="list-group-item")
    if actions:
        lastaction = actions[-1]

        # Try to parse the most recent modification date from it:
        actiontext = lastaction.text
        match = re.search('Calendar Day: (\d\d/\d\d/\d\d\d\d)', actiontext)
        if match:
            last_action_date = dateutil.parser.parse(match.group(1))
        else:
            last_action_date = None
        billdic['last_action_date'] = last_action_date

        # nmlegis erroneously uses <br>blah</br><strong> and
        # apparently assumes browsers will put a break at the </br>.
        # Since that's illegal HTML, BS doesn't parse it that way.
        # But if we don't compensate, the status looks awful.
        # So try to mitigate that by inserting a <br> before <strong>.
        billdic["statusHTML"] = re.sub('<strong>', '<br><strong>',
                                       str(lastaction))

        # Clean up the text in a similar way, adding spaces and line breaks.
        while actiontext.startswith('\n'):
            actiontext = actiontext[1:]
        actiontext = '    ' + actiontext
        actiontext = re.sub('(Legislative Day: [0-9]*)', '\\1\n    ',
                            actiontext)
        actiontext = re.sub('(Calendar Day: ../../....)', '\\1\n    ',
                            actiontext)
        actiontext = re.sub('\n\n*', '\n', actiontext)
        billdic["statustext"] = actiontext.strip() + '\n' + actioncode.strip()

    # The bill's page has other useful info, like votes, analysis etc.
    # but unfortunately that's all filled in later with JS and Ajax so
    # it's invisible to the billtracker. And it's difficult to check
    # directly, because FIR/LESC/amendment documents have random numbers
    # of zeros added to their names.
    # But /api/refresh_legisdata can fill in that data later
    # by scanning the document indexes to see what files exist.
    billdic['FIRlink'] = None
    billdic['LESClink'] = None

    billdic['update_date'] = datetime.datetime.now()
    billdic['mod_date'] = None

    return billdic


def update_legislative_session_list():
    """Read the list of legislative sessions from the legislative website.
    """
    # This file can't import the Flask models (circular dependence),
    # so instead, return a list of dicts, in the order read.
    leg_sessions = []
    try:
        soup = billrequests.soup_from_cache_or_net(
            "https://www.nmlegis.gov/Legislation/Legislation_List",
            cachesecs=60*60*24)
        sessionselect = soup.find("select", id="MainContent_ddlSessionStart")
        # The first option listed is the most recent one.
        # But read all of them, in order to update the cache sessions file.
        options = sessionselect.findAll("option")
        for opt in options:
            # This will be something like:
            # <option value="60">2020 2nd Special</option>
            # <option value="57">2019 Regular</option>
            sessionid = int(opt["value"])

            lsess = { "id": sessionid }

            sessionname = opt.get_text()
            space = sessionname.find(" ")
            lsess["year"] = int(sessionname[:space])
            lsess["typename"] = sessionname[space+1:]
            if lsess["typename"] == "Regular":
                typecode = ""
            elif lsess["typename"] == "Special" or \
                 lsess["typename"] == "1st Special":
                typecode = "s"
            elif lsess["typename"] == "2nd Special":
                typecode = "s2"
            elif lsess["typename"] == "Extraordinary":
                typecode = "x"
            # There hasn't yet been a third special, but it could happen
            elif lsess["typename"] == "3rd Special":
                typecode = "s3"
            year = lsess["year"] - 1900
            if year >= 100:
                year -= 100
            lsess["yearcode"] = "%2d%s" % (year, typecode)

            leg_sessions.append(lsess)

        return leg_sessions

    except:
        print("**** Eek, couldn't determine the legislative session",
              file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return []


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


abbreviations = {
   '*': 'Emergency clause',
   'API.': 'Action postponed indefinitely',
   'CC': 'Conference committee (Senate and House fail to agree)',
   'CS': 'Committee substitute',
   # 'CS/H 18': 'Committee substitute for House Bill 18.',
   'DEAD': 'Bill Has Died',
   'DNP nt adptd': 'Do Not Pass committee report NOT adopted',
   'DNP': 'Do Not Pass committee report adopted',
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
    # 'T': 'On the Speaker’s table by rule (temporary calendar)',
   'tbld': 'Tabled temporarily by motion.',
   'TBLD INDEF.': 'Tabled indefinitely.',
   'VETO(Mar.7).': 'Vetoed by the Governor and date.',
   'w/drn': 'Withdrawn from committee or daily calendar for subsequent action.',
   'w/o rec': 'WITHOUT RECOMMENDATION committee report adopted.',
}


def decode_full_history(actioncode):
    """Decode a bill's full history according to the code specified in
       https://www.nmlegis.gov/Legislation/Action_Abbreviations
       Return a text string, with newlines separating the actions.
    """
    # The history code is one long line, like
    # HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
    # Most actions start with [legislative day] but the first may not.
    out_lines = ["DAY ACTION"]
    for action, legday in action_code_iter(actioncode):
        out_lines.append(decode_history(action, legday))
    return '\n'.join(out_lines)


def decode_history(action, legday):
    """Decode a single history day according to the code specified in
       https://www.nmlegis.gov/Legislation/Action_Abbreviations
       For instance, 'HCPAC/HJC-HCPAC' -> 'Moved to HCPAC, ref HJC-HCPAC'
       Return the decoded text string.
    """
    # Committee changes are listed as NEWCOMM/COMM{,-COMM}
    # where the comms after the slash may be the old committee,
    # the new committee or some other committee entirely.
    # The abbreviations page doesn't explain.
    # However, slashes can also mean other things, e.g.
    #   CS/H 18, DP/a, FAILED/H or S, FL/, fl/aaa, h/fld cncr,
    #   m/rcnsr adptd, rcld frm/h, s/cncrd, s/fld, SCS/H 18, w/drn, w/o rec
    # It seems like committee movements will always have at least three
    # alphabetic characters on either side of the slash.
    match = re.search('([a-zA-Z]{3,})/([-a-zA-Z]{3,})', action)
    if match:
        # if match.start() != 0 or match.end() != len(action):
        #     print("Warning: XXX)
        return ('%4s: Sent to %s, ref %s'
                % (legday, match.group(1), match.group(2)))

    # It's not a committee assignment; decode what we can.
    for code in abbreviations.keys():
        if code in action:
            action = action.replace(code, abbreviations[code])
    return('%4s: %s' % (legday, action))


def most_recent_action(billdic):
    """Return a date, plus text and HTML, for the most recent action
       represented in billdic["statusHTML"].
    """
    if not billdic['statusHTML']:
        return None
    soup = BeautifulSoup(billdic["statusHTML"])
    actions = soup.findAll('span', class_="list-group-item")
    if not actions:
        return None
    lastaction = actions[-1]

    # Try to parse the most recent modification date from t.
    match = re.search('Calendar Day: (\d\d/\d\d/\d\d\d\d)', lastaction)
    if match:
        last_action_date = dateutil.parser.parse(match.group(1))
    else:
        last_action_date = None
    billdic['last_action_date'] = last_action_date
    return last_action_date, str(lastaction), lastaction.text


#
# All Bills for a session: parsed from the Legislation_List page
# plus the hill directories, then kept in an in-memory structure
# with an easily readable cache file as backup,
# since typically this info is needed for all bills at once when
# a user hits the All Bills page.
#

g_all_bills = {}
    # g_all_bills[yearcode][billno] = [title, url, contentslink, amendlink]


def all_bills(sessionid, yearcode, sessionname):
    """Get an OrderedDict of all bills in the given session.
       From https://www.nmlegis.gov/Legislation/Legislation_List?Session=NN
       sessionid a numeric ID used by nmlegis; yearcode is a string e.g. 20s2.
       Mostly this comes from cached files, but periodically those
       cached files will be updated from the Legislation_List URL.

       Returns (allbills, titleschanged)
       where allbills is an OrderedDict of
           billno: ('TITLE', billurl, contentsurl, amendurl)
       and titleschanged is a dict { billno: "old title" }
    """
    # Keep track of bills whose titles change.
    # They'll need to be treated as new bills.
    titleschanged = {}

    # Read in the special cachefile no matter what; use it to
    # decide what the old titles were.
    all_bills_cachefile = '%s/all_bills_%s.txt' % (billrequests.CACHEDIR,
                                                   yearcode)

    if yearcode not in g_all_bills:
        g_all_bills[yearcode] = OrderedDict()
        # XXX Does the leg website ever delete bills? If so, revisit this.

    def read_all_bills_cachefile():
        with open(all_bills_cachefile) as fp:
            for line in fp:
                try:
                    pieces = line.strip().split('|')
                    if len(pieces) == 4:
                        pieces.append("")
                    billno, title, url, billtext, amendlink = pieces
                    g_all_bills[yearcode][billno] = [title, url,
                                                     billtext, amendlink]
                except:
                    print("Bad line in all_bills cache file:", line,
                          file=sys.stderr)
                    continue

        # If the cachefile was only partly populated because some
        # files were missing at the time it was updated, that case
        # won't be detected.

    try:
        filestat = os.stat(all_bills_cachefile)
        if (time.time() - filestat.st_mtime) <= billrequests.CACHESECS:
            # Cache file is recent enough, no need to re-fetch.

            # Is it still in memory?
            if yearcode in g_all_bills and g_all_bills[yearcode]:
                return g_all_bills[yearcode], titleschanged

            # Not cached, but recent. Read in the cachefile and return.
            read_all_bills_cachefile()

            return g_all_bills[yearcode], titleschanged

        else:
            # The cachefile isn't recent enough, but exists.
            # Read it to have a record of the old bill titles.
            read_all_bills_cachefile()


    except Exception as e:
        # cache file probably doesn't exist yet
        print("allbills cache file %s didn't exist" % all_bills_cachefile, e,
              file=sys.stderr)

    # Populate the allbills cache file.
    print("Refreshing the %s bill list" % yearcode, file=sys.stderr)

    baseurl = 'https://www.nmlegis.gov/Legislation'
    url = baseurl + '/Legislation_List?Session=%2d' % sessionid

    # re-fetch if needed. Pass a cache time that's a little less than
    # the one we're using for the all_bills cachefile
    soup = billrequests.soup_from_cache_or_net(
        url, cachesecs=billrequests.CACHESECS-60)
    if not soup:
        print("Couldn't fetch all bills: no soup", file=sys.stderr)
        return None, None

    footable = soup.find('table', id='MainContent_gridViewLegislation')
    # footable is nmlegis' term for this bill table
    if not footable:
        print("Can't read the all-bills list: no footable", file=sys.stderr)
        return None, None

    allbills_billno_pat = re.compile(
        'MainContent_gridViewLegislation_linkBillID.*')
    title_pat = re.compile('MainContent_gridViewLegislation_lblTitle.*')

    for tr in footable.findAll('tr'):
        billno_a = tr.find('a', id=allbills_billno_pat)
        title_a = tr.find('span', id=title_pat)
        if billno_a and title_a:
            # Text under the link might be something like "HB  1"
            # or might have stars, so remove spaces and stars:
            billno_str = billno_a.text.replace(' ', '').replace('*', '')

            # Check whether it's a changed title.
            if yearcode in g_all_bills and \
               billno_str in g_all_bills[yearcode] and \
               g_all_bills[yearcode][billno_str][0] != title_a.text:
                # Title has changed!
                print("%s: title changed to '%s', from '%s'"
                      % (billno_str, title_a.text,
                         g_all_bills[yearcode][billno_str][0]),
                      file=sys.stderr)
                titleschanged[billno_str] = \
                    g_all_bills[yearcode][billno_str][0]
                g_all_bills[yearcode][billno_str][0] = title_a.text

            # Add this billno and billurl to the global list.
            # Don't know the contents or amend urls yet, so leave blank.
            g_all_bills[yearcode][billno_str] \
                = [ title_a.text, baseurl + "/" + billno_a['href'],
                    "", "" ]

    # Whenever the list of all bills is updated, it's a good time to
    # update the full contents and amendments links so there are links
    # for any new bills, to make it easier to decide what's in a bill
    # and whether it's worth following.
    # Rather than parse every bill page (like we do for followed bills),
    # use the index of the directories where links are stored.
    # Typical URL:
    # https://www.nmlegis.gov/Sessions/20%20Special2/bills/senate/SB0001.HTML
    # https://www.nmlegis.gov/Sessions/21%20Regular/Amendments_In_Context/SR01.pdf
    if len(yearcode) == 2:
        sessionlong = "Regular"
    elif yearcode.endswith("s"):
        sessionlong = "Special"
    elif yearcode.endswith("s2"):
        sessionlong = "Special2"
    elif yearcode.endswith("x"):
        sessionlong = "Extraordinary"
    # XXX also in that dir: 11Redistricting, DIY_Redistricting,
    # InterimCommittees ... be ready to update this if clause.
    baseurl = "https://www.nmlegis.gov/Sessions/%s%%20%s" \
        % (yearcode[:2], sessionlong)
    # Under this are directories for house and senate

    def update_bill_links(listingurl, allbills_index, extension):
        """Given the URL for a place where text links or amendments are,
           parse the HTML dir listing, find bill numbers and insert
           each URL as the allbills_index member of that bill in g_all_bills.
        """
        # Under this are names like SB0001.HTML,
        # which are the contents links for bills.
        # But the number of zeroes is inconsistent and unpredictable,
        # so get a listing and remove the zeros.
        soup = billrequests.soup_from_cache_or_net(listingurl)

        for a in soup.findAll('a'):
            href = a.get('href')
            if not href:
                continue
            if not href.lower().endswith(extension):
                continue
            # href is typically something like
            # /Sessions/21%20Regular/bills/house/HB0059.HTML
            # Remove any initial slash:
            while href.startswith("/"):
                href = href[1:]

            # Is it a plain bill number? Exclude amendments, etc.
            try:
                match = bill_file_pat.search(href)
                # group(2) is the extraneous zeros, if any.
                billno = match.group(1) + match.group(3)
                # Weirdly, the web server gives absolute paths as links.
                # So either need to prepend the server domain,
                # or else use url + basename(href).
                g_all_bills[yearcode][billno][allbills_index] = \
                    "https://www.nmlegis.gov/%s" % (href)
            except Exception as e:
                # print("href %s didn't match a bill pat -- skipping" % href,
                #       file=sys.stderr)
                # print(e, file=sys.stderr)
                pass

    # Update all the places we might find bill original or amended text
    for billtype in ("bills", "memorials", "resolutions"):
        for chamber in ("house", "senate"):
            url = "%s/%s/%s" % (baseurl, billtype, chamber)
            update_bill_links(url, 2, ".html")

    # Update amendments_in_context links too:
    update_bill_links("%s/Amendments_In_Context/" % baseurl, 3, ".pdf")

    # Write the new list back to the bill cachefile
    with open(all_bills_cachefile, "w") as outfp:
        for billno in g_all_bills[yearcode]:
            print("%s|%s|%s|%s|%s" % (billno, *g_all_bills[yearcode][billno]),
                  file=outfp)

    # Now g_all_bills[yearcode] is populated, one way or the other
    return g_all_bills[yearcode], titleschanged


house_senate_billno_pat = re.compile('.*_linkBillID_[0-9]*')

def expand_house_or_senate(code, cache_locally=True):
    """Return a dictionary, with keys equivalent to those of
       expand_committee, below. Some fields may be unset.
         code       "House" or "Senate"
         name,      same as code
         meetings:  list of dicts:
             datetime         date of next meeting, time is 00:00
             timestr          time and details for next meeting
             bills            list of billnos
         chair, members: unset
    """
    ret = { 'code': code, 'name': code }
    return ret

    # XXX The rest of this was only for when the PDF parser doesn't get
    # House or Senate floor meetings. Now that it does, this
    # should no longer be needed.

    # # The floorurl pages (below) don't say anything about the meeting date.
    # # But the next meeting's date is encoded into the Floor Calendar PDF
    # # links on the Session Calendar overview page:
    # calendars_url = "https://www.nmlegis.gov/Calendar/Session"
    # if cache_locally:
    #     soup = billrequests.soup_from_cache_or_net(calendars_url)
    # else:
    #     r = billrequests.get(url)
    #     soup = BeautifulSoup(r.text, 'lxml')

    # def get_date_from_floor_link(chamber, soup):
    #     """chamber is "House" or "Senate. Return pdf_url, yyyy-mm-dd"""
    #     href = None
    #     try:
    #         floorlink = soup.find('a', {
    #             "id": "MainContent_dataList%sCalendarFloor_linkFloorCalendar_0"
    #                    % chamber
    #         })
    #         href = 'https://www.nmlegis.gov' + floorlink.get('href')
    #         # href="/Agendas/Floor/hFloor021222.pdf?t=637803128677866884"
    #         floorlinkpat = ".*/Floor/%sFloor([0-9]{6})\.pdf.*" \
    #             % chamber[0].lower()
    #         m = re.match(floorlinkpat, href)
    #         mmddyy = m.group(1)
    #         # return datetime.date(int(mmddyy[4:]) + 2000,
    #         #                      int(mmddyy[2:4]),
    #         #                      int(mmddyy[:2]))
    #         return href, \
    #             '20%s-%s-%s' % (mmddyy[4:], mmddyy[2:4], mmddyy[:2])
    #     except:
    #         print("Couldn't get floor PDF link", file=sys.stderr)
    #         return href, 0

    # # Some fields that, for committees, are picked up by parsing the
    # # PDF agendas. But the house/senate PDF agendas don't reliably list time.
    # pdf_url, yyyymmdd = get_date_from_floor_link(code, soup)
    # ret['meetings'] = [ {
    #     'datetime': yyyymmdd,
    #     'url': pdf_url,
    #     'zoom': 'https://sg001-harmony.sliq.net/00293/harmony',
    #     'bills': []
    # } ]

    # # Now we're done with the calendars URL.
    # # The bills come from the HTML Floor_Calendar page.
    # floorurl = "https://www.nmlegis.gov/Entity/%s/Floor_Calendar" % code
    # if cache_locally:
    #     soup = billrequests.soup_from_cache_or_net(floorurl)
    # else:
    #     r = billrequests.get(url)
    #     soup = BeautifulSoup(r.text, 'lxml')

    # # House and Senate meeting times aren't listed on their schedule pages --
    # # you just have to know. Both of them can meet at any time of day;
    # # in 2021, 11am is a common Senate meeting time, 2pm is common for
    # # the House and the House almost never meets before noon, but the
    # # times given here are just a wild guess, and instead of showing
    # # exact times to the user, we'll show a link to the only official
    # # meeting time, the one on the PDF schedules. Even that is just an
    # # early boundary, since they often meet as much as several hours late.
    # for a in soup.findAll('a', { "id": house_senate_billno_pat }):
    #     ret['meetings'][0]['bills'].append(a.text.replace(' ', '')
    #                                         .replace('*', ''))
    # return ret


# Patterns needed for parsing committee pages
tbl_bills_scheduled = re.compile("MainContent_formViewCommitteeInformation_gridViewScheduledLegislation")

tbl_committee_mtg_dates = re.compile("MainContent_formViewCommitteeInformation_repeaterCommittees_repeaterDates_0_lblHearingDate_[0-9]*")
tbl_committee_mtg_times = re.compile("MainContent_formViewCommitteeInformation_repeaterCommittees_repeaterDates_0_lblHearingTime_[0-9]*")
tbl_committee_mtg_bills = re.compile("MainContent_formViewCommitteeInformation_repeaterCommittees_repeaterDates_0_gridViewBills_[0-9]+")

billno_cell_pat = re.compile('MainContent_formViewCommitteeInformation_gridViewScheduledLegislation_linkBillID_[0-9]*')

sched_date_pat = re.compile('MainContent_formViewCommitteeInformation_gridViewScheduledLegislation_lblScheduledDate_[0-9]*')


# Pattern for a time followed by optional am, AM, a.m. etc.
# optionally preceded by a date or day specifier like "Tuesday & Thursday"
mtg_datetime_pat = re.compile("(.*) *(\d{1,2}): *(\d\d) *([ap]\.?m\.?)?",
                              flags=re.IGNORECASE)


def expand_committee(code):
    """Return a dictionary, with keys
           code       str, short committee code
           name,      str, human-readable name
           chair      str, legislator code
           members    list of legislator codes
    """
    if code == 'House' or code == 'Senate':
        return expand_house_or_senate(code)

    url = 'https://www.nmlegis.gov/Committee/Standing_Committee?CommitteeCode=%s' % code
    soup = billrequests.soup_from_cache_or_net(url)

    if not soup:
        return None

    # The all-important committee code
    ret = { 'code': code }

    # Committee name
    namespan = soup.find(id="MainContent_formViewCommitteeInformation_lblCommitteeName")
    if not namespan:
        print("Committee", code, "seems to be inactive", file=sys.stderr)
        return

    ret['name'] = namespan.text

    # Now get the list of members:
    members = []
    membertbl = soup.find('table', id='MainContent_formViewCommitteeInformation_gridViewCommitteeMembers')
    if membertbl:
        for row in membertbl.findAll('tr'):
            cells = row.findAll('td')
            if cells:
                # members.append([cells[1].text.strip(), cells[0].text.strip(),
                #                 cells[-1].text.strip()])
                # This is name, title, role.
                # But we really need the sponcode rather than the name
                sponcode = None
                sponcode_a = cells[1].find('a')
                if sponcode_a:
                    href = sponcode_a.get('href')
                    match = re.search('.*SponCode=([A-Z]*)', href)
                    if match:
                        sponcode = match.group(1)
                        members.append(sponcode)
                        if cells[-1].text.strip() == 'Chair':
                            ret['chair'] = sponcode
        ret['members'] = members

    return ret


def expand_committees(jsonsrc=None):
    """Expand all committees that have meetings upcoming,
       updating meeting dates from the latest PDF schedules.

       Return a dictionary of dictionaries, with the outer one keyed
       by committee code.
       Each inner dict has  keys:
           name,      str, human-readable name
           chair      str, legislator code
           members    list of legislator codes
           meetings:  list of dicts:
               datetime         datetime for meeting (might be just a date)
               timestr          time and details for next meeting
               bills            list of billnos
          (Currently the meetings list will have only one item:
          we don't handle multiple meetings yet.)
    """
    thisyear = datetime.date.today().year

    # Ed Santiago has a perl script, nmlegis-get-calendars,
    # https://gitlab.com/edsantiago/nmlegis
    # that parses the PDF schedules that are really the only reliable
    # way to get committee meeting times and bill lists.
    # It's run once an hour to update the indicated URL.
    if not jsonsrc:
        jsonsrc = "http://nmlegis.edsantiago.com/schedule.json"

    # XXX Eventually should check to make sure it's being kept
    # up to date and at least some dates are in the future.
    # h = requests.get(pdf_cal_url).headers["Last-Modified"]
    # is something like "Sun, 06 Feb 2022 21:55:07 GMT"
    # the strftime format is "%a, %d %b %Y %H:%M:%S GMT"
    # but billrequests doesn't yet handle head() properly
    if jsonsrc.startswith("http") and ':' in jsonsrc:
        r = requests.get(jsonsrc)
        scheduledata = r.json()
    else:
        with open(jsonsrc) as jfp:
            scheduledata = json.load(jfp)

    # nmlegis-get-calendars doesn't currently handle House or Senate floors.
    # Add those separately; they'll be expanded by expand_committee
    # which calls expand_house_or_senate
    # scheduledata["House"] = {}
    # scheduledata["Senate"] = {}

    # Rename "H Floor" to "House" and likewise for Senate
    if "H Floor" in scheduledata:
        scheduledata["House"] = scheduledata.pop("H Floor")
    if "S Floor" in scheduledata:
        scheduledata["Senate"] = scheduledata.pop("S Floor")

    committees = {}

    for commcode in scheduledata:
        if commcode == "_schema":
            continue

        commdict = expand_committee(commcode)
        if not commdict:
            print("Couldn't expand committee", commdict, file=sys.stderr)
            continue
        committees[commcode] = commdict
        # Now committees[commcode] has everything except meeting times.

        committees[commcode]["meetings"] = []

        for meetingdate in scheduledata[commcode]:
            for mtg in scheduledata[commcode][meetingdate]:
                # Are there bills? If no, don't care about this meeting
                if "bills" not in mtg:
                    continue

                meeting = {}

                # meeting["timestr"] is a human-readable time (no date)
                # that doesn't need to be parseable,
                # e.g. it might be "9:30" but it also might be
                # "1:30 or half an hour after floor session".
                if "time" in mtg:
                    meeting["timestr"] = mtg["time"]
                else:
                    meeting["timestr"] = ""

                # Parse datetime field, which is in ISO format
                # but may be date only or date and time.
                # Replace datetime or date field.
                try:
                    if 'T' in mtg["datetime"]:
                        meeting["datetime"] = datetime.datetime.strptime(
                            mtg["datetime"],
                            "%Y-%m-%dT%H:%M:%S")
                        if not meeting["timestr"]:
                            meeting["timestr"] \
                                = meeting["datetime"].strftime("%H:%M")
                    # There may or may not be a time; if there wasn't,
                    # parse only the date portion. H and M will be zero.
                    else:
                        meeting["datetime"] = datetime.datetime.strptime(
                            mtg["datetime"],
                            "%Y-%m-%d")

                except KeyError:
                    # No datetime, fall back on date
                    if "date" not in mtg:
                        print("EEK! No 'date' field in", mtg, file=sys.stderr)
                        continue
                    meeting["datetime"] = datetime.datetime.strptime(
                        mtg["date"], "%Y-%m-%d")

                except RuntimeError:
                    print("Couldn't parse meeting datetime from",
                          scheduledata[commcode], file=sys.stderr)
                    continue

                # Now there's a datetime. Are there bills?
                try:
                    meeting["bills"] = mtg["bills"]
                except:
                    print("No bills for meeting", scheduledata[commcode],
                          file=sys.stderr)
                    continue

                # Add more to the the free-form "timestr" field.

                # Start with a nice human-friendly date
                # meeting["time"] = meeting["datetime"].strftime("%a, %b %d ")
                # then add the human-readable, but maybe unparseable, time:
                if 'room' in mtg:
                    meeting["timestr"] += ", room %s" \
                        % mtg['room']
                if 'zoom' in mtg:
                    meeting["timestr"] \
                        += ", <a href='%s' target='_blank'>zoom link</a>" \
                           % mtg['zoom']
                elif commcode == "House" or commcode == "Senate":
                    meeting["timestr"] \
                        += ", <a href='https://sg001-harmony.sliq.net/00293/" \
                           "harmony' target='_blank'>view on sliq</a>"
                if 'url' in mtg:
                    meeting["timestr"] \
                        += ", <a href='%s' target='_blank'>PDF schedule</a>" \
                           % mtg['url']

                committees[commcode]["meetings"].append(meeting)

    return committees


def get_sponcodes(url):
    legs = {}
    r = billrequests.get(url)
    if not r or not r.text:
        print("ERROR: Couldn't fetch", url, file=sys.stderr)
        return legs
    soup = BeautifulSoup(r.text, 'lxml')
    select = soup.find(id="MainContent_ddlLegislators")
    for opt in select.findAll('option'):
        value = opt.get('value')
        if value == "...":
            continue
        legs[value] = opt.text
    return legs


def get_legislator_list():
    """Fetches Legislators.XLS from the legislative website;
       returns a list of dictionaries.
    """
    houseurl = 'https://www.nmlegis.gov/Members/Legislator_List?T=R'
    senateurl = 'https://www.nmlegis.gov/Members/Legislator_List?T=S'
    house_sponcodes = get_sponcodes(houseurl)
    senate_sponcodes = get_sponcodes(senateurl)

    # url = 'ftp://www.nmlegis.gov/Legislator%20Information/Legislators.XLS'
    cachefile = '%s/%s' % (billrequests.CACHEDIR, 'Legislators.XLS')

    billrequests.ftp_get('www.nmlegis.gov', 'Legislator Information',
            'RETR Legislators.XLS', outfile=cachefile)

    # xlrd gives
    # WARNING *** OLE2 inconsistency: SSCS size is 0 but SSAT size is non-zero
    # but still seems to work okay.
    wb = xlrd.open_workbook(cachefile)
    sheet = wb.sheet_by_name(wb.sheet_names()[0])
    if not sheet or sheet.ncols <= 0 :
        print("Null sheet, couldn't read", cachefile, file=sys.stderr)
        return

    wanted_fields = [ "FNAME", "LNAME", "TITLE",
                      "STREET", "CITY", "STATE", "ZIP",
                      "OFF_PHONE", "OFF_ROOM", "WKPH", "HMPH",
                      "PreferredEmail" ]
    to_fields = [ "firstname", "lastname", "title",
                  "street", "city", "state", "zip",
                  "office_phone", "office", "work_phone", "home_phone",
                  "email" ]

    fields = [ sheet.cell(0, col).value for col in range(sheet.ncols) ]

    legislators = []

    for row in range(1, sheet.nrows):
        leg = {}
        for i, f in enumerate(wanted_fields):
            leg[to_fields[i]] = sheet.cell(row, fields.index(f)).value

        fullname = leg['firstname'] + ' ' + leg['lastname']

        sponcode = None
        for sp in senate_sponcodes:
            if fullname == senate_sponcodes[sp]:
                sponcode = sp
                break
        if not sponcode:
            for sp in house_sponcodes:
                if fullname == house_sponcodes[sp]:
                    sponcode = sp
                    break
        if sponcode:
            # print("%s: %s" % (sp, fullname))
            leg['sponcode'] = sponcode
            legislators.append(leg)
        else:
            print("**** no sponcode: %s" % (fullname), file=sys.stderr)

    return legislators

"""
ftp://www.nmlegis.gov/ has the following directories:

bills, memorials, resolutions
  house, senate
    e.g. HB0001.pdf

firs, LESCAnalysis
  e.g. HB0001.PDF
  e.g. HB0005.PDF

Amendments_In_Context
  e.g. HB0001.pdf
Floor_Amendments
  e.g. SB0048SFL1.pdf

Legislator Information
  (already being parsed)

Not needed (yet):
final
ExecMessages
votes

Probably never needed:
LFCForms
capitaloutlays
other
"""


#
# __main__ doesn't work any more because of the relative import .billutils.
#
if __name__ == '__main__':
    update_legislator_list()

    sys.exit(0)

    bills, member = expand_committee('SCORC')
    print("Scheduled bills:", bills)
    print("Members:", members)

    def print_bill_dic(bd):
        print("%s: %s" % (bd['billno'], bd['title']))
        print("Current location: %s --> %s" % (bd['curloc'],
                                               bd['curloclink']))
        print("Sponsor: %s --> %s" % (bd['sponsor'], bd['sponsorlink']))

    billdic = parse_bill_page('HJR1')
    print_bill_dic(billdic)
