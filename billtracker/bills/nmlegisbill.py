#!/usr/bin/env python3

from __future__ import print_function

from .billutils import current_leg_year, year_to_2digit, billno_to_parts, \
      URLmapper, ftp_get, ftp_index

# Scrape bill data from bill pages from nmlegis.org.

import sys, os
import datetime, dateutil.parser
import time
import re
import requests
import posixpath
from collections import OrderedDict
from bs4 import BeautifulSoup
import xlrd
import traceback

url_mapper = URLmapper('https://www.nmlegis.gov',
    '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')


def check_analysis(billno):
    '''See if there are any FIR or LESC analysis links.
       The bill's webpage won't tell us because those are hidden
       behind Javascript, so just try forming URLs and see if
       anything's there.
    '''
    (chamber, billtype, number, year) = billno_to_parts(billno)
    # number = int(number)

    # XXX This urlmapper stuff needs to be redesigned.
    # The to_local_link stuff here is just to keep us from
    # hitting a remote server while running tests.
    firlink = url_mapper.to_local_link(
        '%s/Sessions/%s%%20Regular/firs/%s%s000%s.PDF' \
        % (url_mapper.baseurl, year, chamber, billtype, number),
        None)
    lesclink = url_mapper.to_local_link(
        '%s/Sessions/%s%%20Regular/LESCAnalysis/%s%s000%s.PDF' \
               % (url_mapper.baseurl, year, chamber, billtype, number),
        None)
    amendlink = url_mapper.to_local_link(
        '%s/Sessions/%s%%20Regular/Amendments_In_Context/%s%s000%s.PDF' \
               % (url_mapper.baseurl, year, chamber, billtype, number),
        None)

    # The legislative website doesn't give errors for missing PDFs;
    # instead, it serves a short HTML page instead of a PDF.
    # (Maybe unclear on how to do a custom 404 page?)
    def check_for_pdf(url):
        # print("PDF url:", url)
        if not url or ':' not in url:
            return None
        request = requests.head(url)
        if request.status_code != 200:
            # print("Bad status code")
            return None
        if request.headers['Content-Type'] != 'application/pdf':
            # print("Bad Content-Type:", request.headers['Content-Type'])
            return None
        return url

    firlink = check_for_pdf(firlink)
    lesclink = check_for_pdf(lesclink)
    amendlink = check_for_pdf(amendlink)

    return firlink, lesclink, amendlink


def bill_url(billno, billyear):
    chamber, billtype, number, year = billno_to_parts(billno,
                                          year=year_to_2digit(billyear))

    return 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' % (chamber, billtype, number, year)


cachedir = 'cache'

def url_to_cache_filename(billurl):
    return billurl.replace('https://www.nmlegis.gov/', '') \
                  .replace('/Legislation', '') \
                  .replace('/', '_') \
                  .replace('?', '_') \
                  .replace('&', '_')

def soup_from_cache_or_net(baseurl, cachefile=None, cachesecs=2*60*60):
    '''baseurl is a full URL including https://www.nmlegis.gov/
       or a full URL including that part.
       If we have a recent cached version, use it,
       otherwise fetch the file and cache it.
       If the cache file is older than cachesecs, replace it.
       Either way, return a BS soup of the contents.
    '''
    if not os.path.exists(cachedir):
        try:
            os.mkdir(cachedir)
        except:
            print("Couldn't create cache dir", cachedir, "-- not caching")

    if not cachefile:
        cachefile = '%s/%s' % (cachedir, url_to_cache_filename(baseurl))

    # Use cached pages so as not to hit the server so often.
    if os.path.exists(cachefile):
        filestat = os.stat(cachefile)
        if (time.time() - filestat.st_mtime) < cachesecs or cachesecs < 0:
            print("Already cached:", baseurl, '->', cachefile, file=sys.stderr)
            baseurl = cachefile

    if ':' in baseurl:
        print("Re-fetching: cache has expired on", baseurl, file=sys.stderr)

        # billdic['bill_url'] = url_mapper.to_abs_link(baseurl, baseurl)
        try:
            # Use a timeout here.
            # When testing, it's useful to reduce this timeout a lot.
            r = requests.get(baseurl, timeout=30)
            soup = BeautifulSoup(r.text, 'lxml')
        except Exception as e:
            print("Couldn't fetch", baseurl, ":", e)
            soup = None

        if not soup:
            return None

        # Python 3 these days is supposed to use the system default
        # encoding, I thought, but sometimes it doesn't and dies
        # trying to write to the cache file unless you specify
        # an encoding explicitly:
        with open(cachefile, "w", encoding="utf-8") as cachefp:
            # r.text is str and shouldn't need decoding
            cachefp.write(r.text)
            # cachefp.write(r.text.decode())
            print("Cached locally as %s" % cachefile, file=sys.stderr)

    else:
        with open(baseurl, encoding="utf-8") as fp:
            # billdic['bill_url'] = baseurl
            soup = BeautifulSoup(fp, 'lxml')

        # This probably ought to be folded into the url mapper somehow.
        # baseurl = "http://www.nmlegis.gov/Legislation/Legislation"

    return soup

scheduled_for_pat = re.compile("Scheduled for.*on ([0-9/]*)")

def parse_bill_page(billno, year, cache_locally=True, cachesecs=2*60*60):
    '''Download and parse a bill's page on nmlegis.org.
       Return a dictionary containing:
       chamber, billtype, number, year, title, sponsor, sponsorlink,
       location.
       Set update_date to now.

       If cache_locally, will save downloaded files to local cache.
       Will try to read back from cache if the cache file isn't more
       than 2 hours old.

       Does *not* save the fetched bill back to the database.
    '''
    billdic = { 'billno': billno }
    (billdic['chamber'], billdic['billtype'],
     billdic['number'], billdic['year']) = billno_to_parts(billno, year)

    baseurl = 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' \
        % (billdic['chamber'], billdic['billtype'],
           billdic['number'], billdic['year'])

    # baseurl = url_mapper.bill_url(billdic['chamber'],
    #                               billdic['billtype'],
    #                               billdic['number'],
    #                               billdic['year'])

    if cache_locally:
        cachefile = os.path.join(cachedir,
                                 '20%s-%s.html' % (billdic['year'], billno))
        soup = soup_from_cache_or_net(baseurl, cachefile=cachefile,
                                      cachesecs=cachesecs)
    else:
        r = requests.get(baseurl)
        soup = BeautifulSoup(r.text, 'lxml')

    # If something failed -- for instance, if we got an empty file
    # or an error page -- then the title span won't be there.
    # Detect that:
    try:
        billdic['title'] = soup.find("span",
            id="MainContent_formViewLegislation_lblTitle").text
    except AttributeError:
        print("Couldn't find title span")
        # If we cached, remove the cache file.
        if cache_locally and cachefile:
            os.unlink(cachefile)
        return None

    sponsor_a = soup.find("a",
                          id="MainContent_formViewLegislation_linkSponsor")
    billdic['sponsor'] = sponsor_a.text.strip()
    billdic['sponsorlink'] = url_mapper.to_abs_link(sponsor_a.get('href'),
                                                    baseurl)

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
        # curloc text if the bill is scheduled.
        # Sometimes that's the only clue to scheduling, so look for it.
        scheduled_for = scheduled_for_pat.match(curloc_text)
        if scheduled_for:
            schedstr = scheduled_for.group(1)
            print(billdic['billno'], "is scheduled for", schedstr,
                  file=sys.stderr)
            try:
                billdic['scheduled_date'] = dateutil.parser.parse(schedstr)
                print("Scheduled for", billdic['scheduled_date'])
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
                if requests.head(html_cs).status_code == 200:
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
    # it's invisible to us. But we can make a guess at FIR and LESC links.
    # Ignore the amendlink passed back, since we set that earlier.
    billdic['FIRlink'], billdic['LESClink'], otheramend \
        = check_analysis(billno)
    # print("Checked analysis:", billdic['FIRlink'], billdic['LESClink'],
    #       billdic['amendlink'], file=sys.stderr)

    billdic['update_date'] = datetime.datetime.now()
    billdic['mod_date'] = None

    return billdic


def action_code_iter(actioncode):
    '''Iterate over an action code, like
       HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
       Yield each (action, leg_day) one by one.
       If an action (e.g. the first one) doesn't start with [leg_day],
       return 0 for that day.
    '''
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

committeecodes = {
   'HAFC': 'Appropriations & Finance',
   'HAGC': 'House Agriculture & Water Resources Committee',
   'HAWC': 'Agriculture, Water & Wildlife',
   'HBEC': 'Business & Employment',
   'HBIC': 'House Business & Industry Committee',
   'HCEDC': 'COMMERCE & ECONOMIC DEVELOPMENT COMMITTEE',
   'HCPAC': 'House Consumer & Public Affairs Committee',
   'HE&EC': 'Enrolling & Engrossing',
   'HEC': 'Education',
   'HEEC': 'House Enrolling & Engrossing Committee',
   'HEENC': 'Energy, Environment & Natural Resources',
   'HENRC': 'House Energy & Natural Resources Committee',
   'HGEIC': 'Government, Elections & Indian Affairs',
   'HGUAC': 'House Government & Urban Affairs',
   'HHC': 'Health',
   'HHGAC': 'House Health & Government Affairs Committee',
   'HHGIC': 'House Health, Government & Indian Affairs Committee',
   'HHHC': 'HOUSE HEALTH & HUMAN SERVICES',
   'HJC': 'Judiciary',
   'HLC': 'House Labor & Human Resources Committee',
   'HLEDC': 'HOUSE LABOR & ECONOMIC DEVELOPMENT',
   'HLELC': 'HOUSE LOCAL GOVERNMENT, ELECTIONS, LAND GRANTS & CULTURAL AFFAIRS',
   'HLLC': 'LOCAL GOVERNMENT, LAND GRANTS & CULTURAL AFFAIRS',
   'HLVMC': 'LABOR, VETERANS\' AND MILITARY AFFAIRS COMMITTEE',
   'HRC': 'Rules & Order of Business',
   'HRPAC': 'Regulatory & Public Affairs',
   'HSCAC': 'Safety & Civil Affairs',
   'HSEIC': 'STATE GOVERNMENT, ELECTIONS & INDIAN AFFAIRS COMMITTEE',
   'HSIVC': 'HOUSE STATE GOVERNMENT, INDIAN & VETERANS\' AFFAIRS',
   'HTC': 'House Transportation Committee',
   'HTPWC': 'Transportation & Public Works',
   'HTRC': 'House Taxation & Revenue Committee',
   'HVEC': 'House Voters & Elections Committee',
   'HWMC': 'Ways & Means',
   'SCONC': 'Conservation',
   'SCORC': 'Corporations & Transportation',
   'SEC': 'Education',
   'SFC': 'Finance',
   'SGC': 'Senate Select Gaming Committee',
   'SIAC': 'Indian & Cultural Affairs',
   'SJC': 'Judiciary',
   'SPAC': 'Public Affairs',
   'SRC': 'Rules',
   'SWMC': 'Senate Ways & Means Committee',
}


def decode_full_history(actioncode):
    '''Decode a bill's full history according to the code specified in
       https://www.nmlegis.gov/Legislation/Action_Abbreviations
       Return a text string, with newlines separating the actions.
    '''
    # The history code is one long line, like
    # HPREF [2] HCPAC/HJC-HCPAC [3] DNP-CS/DP-HJC [4] DP [5] PASSED/H (40-29) [8] SPAC/SJC-SPAC [17] DP-SJC [22] DP/a [23] FAILED/S (18-24).
    # Most actions start with [legislative day] but the first may not.
    out_lines = ["DAY ACTION"]
    for action, legday in action_code_iter(actioncode):
        out_lines.append(decode_history(action, legday))
    return '\n'.join(out_lines)


def decode_history(action, legday):
    '''Decode a single history day according to the code specified in
       https://www.nmlegis.gov/Legislation/Action_Abbreviations
       For instance, 'HCPAC/HJC-HCPAC' -> 'Moved to HCPAC, ref HJC-HCPAC'
       'DNP-CS/DP-HJC' -> XXXXXX
       Return the decoded text string.
    '''
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
    '''Return a date, plus text and HTML, for the most recent action
       represented in billdic["statusHTML"].
    '''
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

def all_bills(leg_year=None):
    '''Return an OrderedDict of all bills, billno: [title, url]
       From https://www.nmlegis.gov/Legislation/Legislation_List?Session=NN
    '''
    baseurl = 'https://www.nmlegis.gov/Legislation/'

    # Map year to session. 2019 is 57.
    if not leg_year:
        leg_year = current_leg_year()
    session = leg_year - 1962
    url = baseurl + 'Legislation_List?Session=%2d' % session

    # re-fetch once an hour:
    soup = soup_from_cache_or_net(url, cachesecs=60*60)
    if not soup:
        print("Couldn't fetch all bills: network problem")
        return None

    footable = soup.find('table', id='MainContent_gridViewLegislation')
    if not footable:
        print("Can't read the all-bills list: no footable", file=sys.stderr)
        return None

    allbills = OrderedDict()
    billno_pat = re.compile('MainContent_gridViewLegislation_linkBillID.*')
    title_pat = re.compile('MainContent_gridViewLegislation_lblTitle.*')
    for tr in footable.findAll('tr'):
        billno_a = tr.find('a', id=billno_pat)
        title_a = tr.find('span', id=title_pat)
        if billno_a and title_a:
            # Remove spaces and stars:
            allbills[billno_a.text.replace(' ', '').replace('*', '')] \
                = [ title_a.text, baseurl + billno_a['href'] ]

    return allbills

# Link lists from contents_url_for_parts
# A dictionary with keys of 'SB', 'HB', 'SJR' etc.
# each of whose contents are a dictionary of int billno: url.
Link_lists = {}

def populate_link_lists(url, chambertype, cachetime):

    # XXX Currently, the link lists are only used for /allbills,
    # where the various links aren't already known,
    # and then only when there are bills that haven't been
    # seen before in the link_lists.
    # It might be worth considering keeping link lists around
    # for use in other functions like bill_url_from_parts;
    # but in this case, it would be important to store the
    # time the link lists were fetched, to expire them properly,
    # since late in the session additional links like FIR reports
    # and committee substitutions might appear more often than
    # new bills.
    print("populate_link_lists(", url, chambertype, ")",
          file=sys.stderr)

    soup = soup_from_cache_or_net(url, cachesecs=cachetime)
    if chambertype not in Link_lists:
        Link_lists[chambertype] = {}

    for a in soup.findAll('a'):
        href = a.get('href')
        if not href.endswith('.HTML'):
            continue
        if not href.startswith('/Sessions/'):
            continue
        href = url_mapper.to_abs_link(href, url)

        base, ext = os.path.splitext(os.path.basename(href))
        # base is now something like HJM005
        match = re.search('([A-Z]*)([0-9]*)', base)
        if match:
            billandtype = match.group(1)
            num = match.group(2)

        # Memorials (e.g. HM) and Joint Memorials (HJM) are in the same
        # directory and shouldn't be mistaken for each other.
        # populate_link_lists is called separately for memorials
        # and joint memorials; this is slightly inefficient
        # but at least the files are cached, not re-downloaded.
        # So here, skip links that aren't of the requested chambertype.
        if billandtype != chambertype:
            continue

        num = int(num)

        # The bill contents directory may have several amendments
        # as well as the original text. E.g. it might have
        # HB0001.HTML, HB0001AF1.HTML and HB0001FC1.HTML.
        # Currently these are sorted so that the base text
        # comes first, so we don't have to sort while inserting.
        if num in Link_lists[chambertype]:
            Link_lists[chambertype][num].append(href)
        else:
            Link_lists[chambertype][num] = [href]

def contents_url_for_parts(chamber, billtype, number, year):
    '''A link to a page with a bill's contents in HTML.
       This alas cannot be inferred from the billno,
       because there is an unpredictable number of zeroes
       inserted in the middle: HR001, HM011, HM0111.
       Returns a list of content URLs, with the first element
       of the list being the contents and the others being amendments
       that are stored in the same directory, which should start with
       the same string as the bill's contents;
       e.g. SJM001.HTML and SJM001RU1.HTML, SM001ES1.HTML
    '''
    chambertype = chamber + billtype    # e.g. HJR
    billnumint = int(number)

    try:
        return Link_lists[chambertype][billnumint]
    except:    # most likely KeyError, but why not catch everything?
        print("Nope, %s%s%s is not in Link_lists" % (chamber, billtype,
                                                     number))
        pass

    # We don't have it cached. Re-fetch the relevant index.

    if chamber == 'S':
        chambername = 'senate'
    else:
        chambername = 'house'

    if billtype[-1] == 'M':
        typedir = 'memorials'
    elif billtype[-1] == 'R':
        typedir = 'resolutions'
    else:
        typedir = 'bills'

    url = 'https://www.nmlegis.gov/Sessions/%s%%20Regular/%s/%s/' % \
        (year, typedir, chambername)

    # Check the relevant directory listing.
    # If these go away, could use the ftp equivalent:
    # ftp://www.nmlegis.gov/resolutions/senate
    # Only re-fetch these twice a day at most:

    # XXX This checks at least the cache every time.
    # It would be nice to find a way around that.
    # Probably need to keep the info in the database.

    populate_link_lists(url, chambertype, 12*60*60)

    # Hope we have it now! But we might not, if it's a bill that's so new
    # that the cache was too old.
    try:
        return Link_lists[chambertype][billnumint]
    except:
        pass

    # If it wasn't in Link_lists, the cache is probably too old. Re-fetch.
    print("Re-fetching the link lists for", url)
    populate_link_lists(url, chambertype, 5*60)
    try:
        return Link_lists[chambertype][billnumint]
    except:
        print("Couldn't get bill text even after re-fetching Link_lists!")
        print(traceback.format_exc())
        if chambertype in Link_lists:
            print("Link_lists[%s] has:" % chambertype,
                  Link_lists[chambertype].keys())
        else:
            print("Link_lists has", Link_lists.keys(), "but not", chambertype)
    return ''

def contents_url_for_billno(billno):
    '''A link to a page with a bill's contents in HTML,
       for bills not yet in the database.
       Returns a list of contents and amendments.
    '''
    (chamber, billtype, number, year) = billno_to_parts(billno)
    return contents_url_for_parts(chamber, billtype, number, year)

def expand_house_or_senate(code, cache_locally=True):
    '''Return a dictionary, with keys code, name, scheduled_bills.
       Other fields that committees would have will be unset.
    '''
    url = 'https://www.nmlegis.gov/Entity/%s/Floor_Calendar' % code
    if cache_locally:
        soup = soup_from_cache_or_net(url, cachesecs=3*60*60)
    else:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, 'lxml')

    ret = { 'code': code, 'name': code }

    billno_pat = re.compile('.*_linkBillID_[0-9]*')
    ret['scheduled_bills'] = []
    for a in soup.findAll('a', id=billno_pat):
        ret['scheduled_bills'].append([a.text.replace(' ', ''), None])

    return ret

def expand_committee(code, cache_locally=True):
    '''Return a dictionary, with keys code, name, mtg_time, chair,
       members, scheduled_bills
    '''

    if code == 'House' or code == 'Senate':
        return expand_house_or_senate(code, cache_locally)

    # XXX Need some other special cases

    url = 'https://www.nmlegis.gov/Committee/Standing_Committee?CommitteeCode=%s' % code
    if cache_locally:
        soup = soup_from_cache_or_net(url, cachesecs=2*60*60)
    else:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, 'lxml')

    # The all-important committee code
    ret = { 'code': code }

    # Committee name
    namespan = soup.find(id="MainContent_formViewCommitteeInformation_lblCommitteeName")
    if namespan:
        ret['name'] = namespan.text

    # Meeting time/place (free text, not parsed)
    timespan = soup.find(id="MainContent_formViewCommitteeInformation_lblMeetingDate")
    if timespan:
        ret['mtg_time'] = timespan.text

    # # Next meeting:
    # next_mtg = ''
    # nextmtg_tbl = soup.find('table',
    #                         id="MainContent_formViewCommitteeInformation")
    # if nextmtg_tbl:
    #     mdate = nextmtg_tbl.find('span',
    #              id="MainContent_formViewCommitteeInformation_lblMeetingDate")
    #     # Time and place of the next scheduled meeting:
    #     if mdate:
    #         next_mtg = mdate.text

    # Loop over bills to be considered:
    scheduled = []
    billstbl = soup.find('table',
                         id="MainContent_formViewCommitteeInformation_gridViewScheduledLegislation")
    if billstbl:
        billno_pat = re.compile('MainContent_formViewCommitteeInformation_gridViewScheduledLegislation_linkBillID_[0-9]*')
        sched_date_pat = re.compile('MainContent_formViewCommitteeInformation_gridViewScheduledLegislation_lblScheduledDate_[0-9]*')
        for row in billstbl.findAll('tr'):
            billno = row.find(id=billno_pat)
            scheduled_date = row.find(id=sched_date_pat)
            if billno and scheduled_date:
                # Bills on these pages have extra spaces, like 'HB 101'.
                # Some of them also start with * for unexplained reasons.
                scheduled.append([billno.text.replace(' ', '').replace('*', ''),
                                  scheduled_date.text.strip()])

        ret['scheduled_bills'] = scheduled
    else:
        print("No bills table found in", url, file=sys.stderr)

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
                            ret['chair'] = cells[1].text.strip()
        ret['members'] = members

    return ret


def get_sponcodes(url):
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'lxml')
    select = soup.find(id="MainContent_ddlLegislators")
    legs = {}
    for opt in select.findAll('option'):
        value = opt.get('value')
        if value == "...":
            continue
        legs[value] = opt.text
    return legs


def get_legislator_list():
    '''Fetches Legislators.XLS from the legislative website;
       returns a list of dictionaries.
    '''
    houseurl = 'https://www.nmlegis.gov/Members/Legislator_List?T=R'
    senateurl = 'https://www.nmlegis.gov/Members/Legislator_List?T=S'
    house_sponcodes = get_sponcodes(houseurl)
    senate_sponcodes = get_sponcodes(senateurl)

    # url = 'ftp://www.nmlegis.gov/Legislator%20Information/Legislators.XLS'
    cachefile = '%s/%s' % (cachedir, 'Legislators.XLS')

    # Seriously? requests can't handle ftp?
    ftp_get('www.nmlegis.gov', 'Legislator Information',
            'RETR Legislators.XLS', outfile=cachefile)

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

'''
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
'''


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
