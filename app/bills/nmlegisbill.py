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
import threading
import traceback


# A bill pattern, allowing for any number of extra leading zeros
# like the FIR/LESC links randomly add.
# If there are other letters or a different pattern,
# it may be an amendment or some other supporting document.
billno_pat = re.compile(r"([SH][JC]{0,1}[BMR])(0*)([1-9][0-9]*)")

# Used in listing the Tabled_Reports directory (may be good for amendments too)
amend_billno_pat = re.compile(r"([SH][JC]{0,1}[BMR])(0*)([1-9][0-9]*)([A-Za-z0-9]*)(\.[a-zA-Z]+)", re.IGNORECASE)

house_senate_billno_pat = re.compile(r'.*_linkBillID_[0-9]*')

# Same thing, but occurring in a file pathname,
# so it should start with / and end with .
bill_file_pat = re.compile(r"([SH][JC]{0,1}[BMR])0*([1-9][0-9]*)\.")

# Patterns used in update_allbills
allbills_billno_pat = re.compile(
    'MainContent_gridViewLegislation_linkBillID.*')
title_pat = re.compile(r'MainContent_gridViewLegislation_lblTitle.*')
sponsor_pat = re.compile(r'MainContent_gridViewLegislation_linkSponsor.*')
sponcode_pat = re.compile(r'.*/Legislator\?SponCode=([A-Z]+)')
action_pat = re.compile(r"MainContent_gridViewLegislation_lblActions_[0-9]")

# Patterns used in parse_bill_page
scheduled_for_pat = re.compile(r"Scheduled for.*on ([0-9/]*)")
sponcode_pat = re.compile(r".*[&?]SponCode\=([A-Z]+)")
cspat = re.compile(r"MainContent_dataListLegislationCommitteeSubstitutes_linkSubstitute.*")


# RE patterns needed for parsing committee pages
tbl_bills_scheduled = re.compile(r"MainContent_formViewCommitteeInformation_gridViewScheduledLegislation")

tbl_committee_mtg_dates = re.compile(r"MainContent_formViewCommitteeInformation_repeaterCommittees_repeaterDates_0_lblHearingDate_[0-9]*")
tbl_committee_mtg_times = re.compile(r"MainContent_formViewCommitteeInformation_repeaterCommittees_repeaterDates_0_lblHearingTime_[0-9]*")
tbl_committee_mtg_bills = re.compile(r"MainContent_formViewCommitteeInformation_repeaterCommittees_repeaterDates_0_gridViewBills_[0-9]+")

billno_cell_pat = re.compile(r'MainContent_formViewCommitteeInformation_gridViewScheduledLegislation_linkBillID_[0-9]*')

sched_date_pat = re.compile(r'MainContent_formViewCommitteeInformation_gridViewScheduledLegislation_lblScheduledDate_[0-9]*')

# Pattern for a time followed by optional am, AM, a.m. etc.
# optionally preceded by a date or day specifier like "Tuesday & Thursday"
mtg_datetime_pat = re.compile(r"(.*) *(\d{1,2}): *(\d\d) *([ap]\.?m\.?)?",
                              flags=re.IGNORECASE)

# Pattern to detect dummy bills from their actions
dummy_pat = re.compile(r"^\[[0-9]+\] *not prntd")
dummy_plus_pat = re.compile(r"^\[[0-9]+\] *not prntd.*\[[0-9]+\]")


# XXX The URLmapper stuff should be killed, with any functionality
# that's still needed moved into billrequests.
url_mapper = URLmapper('https://www.nmlegis.gov',
    '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')

# How long to wait before disregarding a file lock:
LOCK_EXPIRATION_SECS = 60*5
g_allbills_lockfile = {}    # keyed by yearcode


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

#
# Two useful outside links on Ed Santiago's site
#
def bill_overview_url(billno, yearcode):
    return 'https://nmlegiswatch.org/bills/%s.html' % billno

def legislator_summary_url(leg):
    return 'https://nmlegiswatch.org/legislators/%s' % leg.sponcode


# XXX Eventually parse_bill_page should be rendered obsolete,
# once there's a way to get bill location and status from the
# actions code in the Legislation_List page.
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

       Does *not* save anything to the flask database.
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
    try:
        actioncode = soup.find(id='MainContent_tabContainerLegislation_tabPanelActions_formViewActionText_lblActionText').text

        # The all-important part: what was the most recent action?
        actiontable = soup.find("table",
          id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions")

        actions = actiontable.find_all('span', class_="list-group-item")
        if actions:
            lastaction = actions[-1]

            # Try to parse the most recent modification date from it:
            actiontext = lastaction.text
            match = re.search(r'Calendar Day: (\d\d/\d\d/\d\d\d\d)', actiontext)
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
    except Exception as e:
        print("** Exception trying to read action table on bill",
              billdic['billno'], ":", e, file=sys.stderr)
        # billdic['last_action_date'] = None
        # billdic['statustext'] = None
        # billdic['statusHTML'] = None

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
       Return a list of dictionaries that include at least these keys:
       id, year, yearcode, name, typename
    """
    # This file can't import the Flask models (circular dependence),
    # so instead, return a list of dicts, in the order read.
    leg_sessions = []
    try:
        # Unfortunately, Legislation_List has the session ids but not
        # the session codes (e.g. 21s2). BillFinder/Number has the
        # codes but not the IDs. So first loop through BillFinder/Number
        # making a table of name and code, then get the rest
        # from Legislation_List
        soup = billrequests.soup_from_cache_or_net(
            "https://www.nmlegis.gov/Legislation/BillFinder/Number",
            cachesecs=60*60*24)
        sessionselect = soup.find("select", id="MainContent_ddlSessions")
        yearcodes_by_name = {}
        for opt in sessionselect.find_all("option"):
            yearcodes_by_name[opt.get_text()] = opt["value"]

        # Now iterate over Legislation_List
        soup = billrequests.soup_from_cache_or_net(
            "https://www.nmlegis.gov/Legislation/Legislation_List",
            cachesecs=60*60*24)
        sessionselect = soup.find("select", id="MainContent_ddlSessionStart")

        # The first option listed is the most recent one.
        # But read all of them, in order to update the cache sessions file.
        options = sessionselect.find_all("option")
        for opt in options:
            # This will be something like:
            # <option value="60">2020 2nd Special</option>
            # <option value="57">2019 Regular</option>
            sessionid = int(opt["value"])

            lsess = { "id": sessionid }

            sessionname = opt.get_text()
            try:
                lsess["yearcode"] = yearcodes_by_name[sessionname]
            except:
                print("'%s' appears in Legislation_List but not BillFinder"
                      % sessionname, file=sys.stderr)
                continue

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
            # lsess["yearcode"] = "%2d%s" % (year, typecode)

            leg_sessions.append(lsess)

        return leg_sessions

    except:
        print("**** Eek, couldn't determine the legislative session",
              file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return []


#
# All Bills for a session: parsed from the Legislation_List page
# plus the hill directories, then kept in an in-memory structure
# with an easily readable cache file as backup,
# since typically this info is needed for all bills at once when
# a user hits the All Bills page.
#

g_allbills = { "_schema": '20230204' }

# Schema 20230204:
# g_allbills[yearcode] = {
#    "_updated": nnn,
#    "HB17" : {
#      "title": "CUR TITLE",
#      "url": "https://...",
#      "sponsors": [],
#      "actions": "SPREF [1] SEC/SFC-SEC",
#      "contents" = "", "pdf" = "",
#      "amendments" = [],
#      "FIR": "", "LESC": "",
#      "location": "",
#      "status": "",
#      "history": [ ["2023-01-30", "Introduced", "ORIGINAL TITLE"],
#                   ["2023-02-02", "titlechanged", "CUR TITLE" ] ]

# It's saved as JSON in these files (index by yearcode):
g_allbills_cachefile = {}


def save_allbills_json(yearcode):
    """Save g_allbills to the JSON cachefile.
       This should be called after creating g_allbills_lockfile first,
       which should be removed/unlocked afterward.
    """
    if not g_allbills[yearcode]:
        print("Can't save null g_allbills[%s]" % yearcode, file=sys.stderr)
    if yearcode not in g_allbills_cachefile:
        g_allbills_cachefile[yearcode] = os.path.join(
            billrequests.CACHEDIR, 'allbills_%s.json' % (yearcode))

    # Save a daily history.
    todaystr = datetime.date.today().strftime("%Y-%m-%d")
    histfile = os.path.join(billrequests.CACHEDIR,
                            'allbills_%s.json' % todaystr)
    try:
        tmpfile = g_allbills_cachefile[yearcode] + ".tmp"
        with open(tmpfile, "w") as fp:
            json.dump(g_allbills[yearcode], fp, indent=2)
        if os.path.exists(g_allbills_cachefile[yearcode]):
            os.rename(g_allbills_cachefile[yearcode], histfile)
        else:
            print(g_allbills_cachefile[yearcode], "didn't exist before",
                  file=sys.stderr)
        os.rename(tmpfile, g_allbills_cachefile[yearcode])
        print("Saved to", g_allbills_cachefile[yearcode], file=sys.stderr)
    except Exception as e:
        print("*** Problem saving allbills cache file for yearcode", yearcode,
              ":", e, file=sys.stderr)


def update_allbills_if_needed(yearcode, sessionid=None, force_update=False):
    """Decide whether we need to re-read the allbills json file,
       or update that file.
       Normally returns immediately, scheduling an update in another
       thread if needed; will not wait unless force_update == True.
    """
    # print(traceback.format_exc(), file=sys.stderr)
    timenow = time.time()

    if yearcode not in g_allbills_cachefile:
        g_allbills_cachefile[yearcode] = '%s/allbills_%s.json' % (
            billrequests.CACHEDIR, yearcode)

    if yearcode not in g_allbills:
        g_allbills[yearcode] = {}

    try:
        filetime = os.stat(g_allbills_cachefile[yearcode]).st_mtime

        # Is the cachefile newer than g_allbills in memory? Read it in.
        # Need this even if we're going to update it, because we don't
        # want to lose the accumulated history entries.
        # Also initialize if g_allbills hasn't been initialized yet
        # in this session, _updated will be 0.
        if (yearcode not in g_allbills or
            "_updated" not in g_allbills[yearcode] or
            filetime > g_allbills[yearcode]["_updated"]):
            print("Refreshing g_allbills from cache file", file=sys.stderr)
            with open(g_allbills_cachefile[yearcode]) as fp:
                g_allbills[yearcode] = json.load(fp)
                # This is kind of a multiple meaning for _updated:
                # in memory, it means when it was last read from the
                # JSON file, but in the JSON file it represents when
                # the bill page was last fetched.
                g_allbills[yearcode]["_updated"] = int(time.time())

    except FileNotFoundError:
        # There's no cachefile. Hopefully we can schedule its creation.
        print(g_allbills_cachefile[yearcode], "doesn't exist yet",
              file=sys.stderr)
        filetime = 0

    # Now g_allbills[yearcode] contains the most recent list of bills
    # as of whenever the cache file was last written.

    # Make sure there's a sessionid either as an argument or in
    # g_allbills. If neither, return.
    try:
        if not sessionid:
            sessionid = g_allbills[yearcode]["_sessionid"]
        elif "_sessionid" not in g_allbills[yearcode]:
            g_allbills[yearcode]["_sessionid"] = sessionid
    except KeyError:
        print("ERROR: Can't update_allbills without sessionid",
              file=sys.stderr)
        return

    # Is g_allbills cachefile too old and needs to be updated?
    # Or is force_update specified?
    if not force_update and ((timenow - filetime) <= billrequests.CACHESECS):
        # Cache is recent enough, return what was read from it.
        # print("Cache is recent enough, returning", file=sys.stderr)
        return

    # It's old enough to be updated. But is it locked because
    # someone else started an update?
    print("allbills needs an update", file=sys.stderr)
    try:
        # Open g_allbills_lockfile. Only update_allbills should remove it.
        g_allbills_lockfile[yearcode] = g_allbills_cachefile[yearcode] + ".lck"
        os.open(g_allbills_lockfile[yearcode], os.O_CREAT | os.O_EXCL)
        print("Opened the lockfile", g_allbills_lockfile[yearcode],
              file=sys.stderr)

        # If there isn't already a g_allbills[yearcode],
        # then we have to wait until it's created.
        # But if there is one, start an update in the background.
        # XXX Doing the update in the background was leading to the
        # information never propagating out to the saved allbills cache
        # file. The background process needs to be able to rewrite
        # the cache file, or otherwise it should run in the foreground.
        if g_allbills[yearcode]:
            print("Updating allbills in the FOREGROUND", file=sys.stderr)
            update_allbills(yearcode, sessionid)

            # print("Updating all_bills in the background ...",
            #       file=sys.stderr)
            # thread = threading.Thread(
            #     target=lambda: update_allbills(yearcode, sessionid))
            # thread.start()
            # print("Started thread", file=sys.stderr)
        else:
            print("No allbills for", yearcode,
                  "yet; updating in foreground", file=sys.stderr)
            update_allbills(yearcode, sessionid)

        return

    except FileExistsError:
        locktime = os.stat(g_allbills_lockfile[yearcode]).st_ctime
        # Detect stuck locks: has it been locked for
        # more than 5 minutes? If so, discard the lock.
        print("Couldn't update allbills: file is locked",
              g_allbills_lockfile[yearcode], file=sys.stderr)
        if timenow - locktime > LOCK_EXPIRATION_SECS:
            print("Removed lock stuck for", timenow - locktime,
                  "seconds", file=sys.stderr)
            os.unlink(g_allbills_lockfile[yearcode])
        else:
            print("lock has been there for", timenow - locktime,
                  "seconds", file=sys.stderr)


def bill_info(billno, yearcode, sessionid):
    """Return a dictionary for a single bill.
       The info comes from g_allbills and should be updated as needed.
    """
    update_allbills_if_needed(yearcode, sessionid)

    try:
        return g_allbills[yearcode][billno]
    except:
        return None


def all_bills(sessionid, yearcode):
    """Get an OrderedDict of all bills in the given session.
       From https://www.nmlegis.gov/Legislation/Legislation_List?Session=NN
       sessionid a numeric ID used by nmlegis; yearcode is a string e.g. 20s2.
       Mostly this comes from cached files, but periodically those
       cached files will be updated from the Legislation_List URL.

       Returns g_allbills[yearcode]
    """
    # if yearcode not in g_leg_sessions:
    #     g_leg_sessions[yearcode] = sessionid

    update_allbills_if_needed(yearcode, sessionid)

    return g_allbills[yearcode]


def update_allbills(yearcode, sessionid):
    """Fetch and parse Legislation_List?Session=NN (numeric session id)
       to update the global g_allbills[yearcode]
       and save to g_allbills_cachefile
       (which should already be initialized with existing bills).
    """
    print("Updating allbills", yearcode, file=sys.stderr)

    baseurl = 'https://www.nmlegis.gov/Legislation'
    url = baseurl + '/Legislation_List?Session=%2d' % sessionid

    todaystr = datetime.date.today().strftime("%Y-%m-%d")

    # re-fetch if needed. Pass a cache time that's a little less than
    # the one we're using for the allbills cachefile
    soup = billrequests.soup_from_cache_or_net(
        url, cachesecs=billrequests.CACHESECS-60)
    if not soup:
        print("Couldn't fetch all bills: no soup", file=sys.stderr)
        return None, None

    footable = soup.find('table', id='MainContent_gridViewLegislation')
    # footable is nmlegis' term for this bill table. Not my fault. :-)
    if not footable:
        print("Can't read the all-bills list: no footable", file=sys.stderr)
        return

    for tr in footable.find_all('tr'):
        billno_a = tr.find('a', id=allbills_billno_pat)
        title_span = tr.find('span', id=title_pat)
        if not billno_a or not title_span:
            continue

        # Text under the link might be something like "HB  1"
        # or might have stars, so remove spaces and stars:
        billno_str = billno_a.text.replace(' ', '').replace('*', '')

        # Add this billno and billurl to the global list if not there already.
        # Don't know the contents or amend urls yet, so leave blank.
        if billno_str not in g_allbills[yearcode]:
            g_allbills[yearcode][billno_str] = {
                "history": [ [ todaystr, "introduced", title_span.text ] ]
            }

        # Update history if title changed.
        if "title" in g_allbills[yearcode][billno_str] and \
           title_span.text != g_allbills[yearcode][billno_str]["title"]:
            if "history" not in g_allbills[yearcode][billno_str]:
                g_allbills[yearcode][billno_str]["history"] = []
            g_allbills[yearcode][billno_str]["history"].append( [
                todaystr, "titlechanged", title_span.text ])

        g_allbills[yearcode][billno_str]["title"] = title_span.text

        g_allbills[yearcode][billno_str]["url"] = \
            baseurl + "/" + billno_a['href']

        # Build sponsor list, replacing what was there before
        # since it might have changed
        g_allbills[yearcode][billno_str]["sponsors"] = []
        for sponsor_a in tr.find_all("a", id=sponsor_pat):
            try:
                g_allbills[yearcode][billno_str]["sponsors"].append(
                    sponcode_pat.match(sponsor_a["href"]).group(1))
            except:
                print("Couldn't match sponcode in", sponsor_a["href"],
                      file=sys.stderr)

        # Action codes
        try:
            actions = tr.find('span', id=action_pat).text
            g_allbills[yearcode][billno_str]["actions"] = actions

            # Try to determine if this is a dummy bill.
            # Dummy bills generally start with "not prntd" as the first action.
            # Dummy bills that are actually being used may not have a title
            # yet, and we can't find out whether they have a committee sub
            # for content without loading their bill page, but we can tell
            # if they've had any actions, like being assigned to a committee.
            # In g_allbills, new dummies have "dummy": True;
            # dummies that have been activated (have had actions)
            # have "dummy" set to the date they became active.

            # Is it a new dummy bill?
            if ("dummy" not in g_allbills[yearcode][billno_str] and
                dummy_pat.match(actions)):
                g_allbills[yearcode][billno_str]["dummy"] = True
                g_allbills[yearcode][billno_str]["history"].append(
                    [ todaystr, "dummyfiled",
                      g_allbills[yearcode][billno_str]["title"] ])

            # Now see if it's an active dummy bill, one with real actions.
            if ("dummy" in g_allbills[yearcode][billno_str] and
                g_allbills[yearcode][billno_str]["dummy"] == True and
                dummy_plus_pat.match(actions)):
                g_allbills[yearcode][billno_str]["dummy"] = todaystr
                g_allbills[yearcode][billno_str]["history"].append(
                    [ todaystr, "dummyactivated", title_span.text ])

        except:
            print("Couldn't get actions for", billno_str, file=sys.stderr)

        # Link to Ed Santiago's bill overview page for every bill.
        # For now, just assume it exists.
        g_allbills[yearcode][billno_str]["overview"] = bill_overview_url(
            billno_str, yearcode)

    # If there are new bills, they'll need content links too.
    # Update them in the background since it involves a lot of fetching
    # from nmlegis, and so will hang for a while when nmlegis goes down.
    # print("Starting background process to update bill links", file=sys.stderr)
    # thread = threading.Thread(
    #     target=lambda: update_bill_links(yearcode))
    # thread.start()
    # XXX Doing the update in the background was leading to the
    # information never propagating out to the saved allbills cache
    # file. The background process needs to be able to rewrite
    # the cache file, or otherwise it should run in the foreground.
    # XXX To avoid all the fetching, the html dirlists should be cached locally.
    print("Updating bill links in FOREGROUND", file=sys.stderr)
    update_bill_links(yearcode)

    # Now bills and links should be up to date,
    # as should g_allbills[yearcode]
    g_allbills[yearcode]["_updated"] = int(time.time())
    save_allbills_json(yearcode)

    print("Finished updating allbills; clearing lockfile", file=sys.stderr)
    os.unlink(g_allbills_lockfile[yearcode])

    return g_allbills


# Updating the list of bills doesn't update the links to bill
# contents and amendments links.
# Rather than parse every bill page (like we do for followed bills),
# use the index of the directories where links are stored.
# Typical URL:
# https://www.nmlegis.gov/Sessions/20%20Special2/bills/senate/SB0001.HTML
# https://www.nmlegis.gov/Sessions/21%20Regular/Amendments_In_Context/SR01.pdf

def update_bill_links(yearcode):
    """Update all relevant bill links found as files at
       https://www.nmlegis.gov/Sessions/23%20Regular/bills/chamber
       where chamber is house or senate.
       Modify g_allbills.
    """
    if len(yearcode) == 2:
        sessionlong = "Regular"
    elif yearcode.endswith("s"):
        sessionlong = "Special"
    elif yearcode[-1].isdigit():
        # it's a special session. Yearcode is something like 21s2;
        # separate the parts before and after the s.
        m = re.search(r'(\d+)s(\d+)$', yearcode)
        if m and len(m.groups())== 2:
            sessionlong = "Special" + m.group(2)
        else:
            print("******* Error: Can't parse session yearcode", yearcode,
                  file=sys.stderr)
            sessionlong = "?"
    elif yearcode.endswith("x"):
        sessionlong = "Extraordinary"

    baseurl = "https://www.nmlegis.gov/Sessions/%s%%20%s" \
        % (yearcode[:2], sessionlong)
    # Under this are these directories (plus a few not less relevant):
    # These dirtypes have files directly in them.
    # Key is dirname, value is what key to use in g_allbills.
    dirs_direct = {
        "firs": "FIR",
        "LESCAnalysis": "LESC",
        "Amendments_In_Context": "Amendments_In_Context",
        "Floor_Amendments": "Floor_Amendments",
    }
    # Tabled_Reports will be dealt with specially

    # These dirs have subdirs house and senate:
    dirs_by_chamber = [ "bills", "memorials", "resolutions" ]
    chambers = [ "house", "senate" ]

    def get_billno_from_filename(amendname):
        """Extract billno from filenames like in Amendments or Tabled_Reports
           which tend to be something like "HB0060CP1T.pdf"
           or may just be a billno with extra zeroes, "SJR002.PDF"
        """
        if amendname.startswith('.'):
            return ''
        m = amend_billno_pat.match(amendname)
        if not m:
            return ''
        return m.group(1).upper() + m.group(3)

    # First do the direct ones.
    for dirtype in dirs_direct:
        listingurl = posixpath.join(baseurl, dirtype)
        nonexistent = set()

        # Under this are filenames like SB0001.HTML,
        # which are the contents links for bills.
        # But the number of zeroes is inconsistent and unpredictable,
        # so get a listing and remove the zeros.
        dirlist = billrequests.get_html_dirlist(listingurl)
        if not dirlist:
            print("No directory listing at", listingurl, file=sys.stderr)
            continue

        for l in dirlist:
            filename = l['name']   # These are names like 'HB0060CP1T.pdf'
            billno = get_billno_from_filename(filename)
            href = l['url']

            if not billno:
                continue
            if billno not in g_allbills[yearcode]:
                nonexistent.add(billno)
                continue

            g_allbills[yearcode][billno][dirs_direct[dirtype]] = href

        if nonexistent:
            print("Nonexistent bills", ', '.join(nonexistent),
                  "reffed in", listingurl, file=sys.stderr)

    # The bill/memorial/resolution dirs are a little more complicated,
    # because they include all kinds of other weird files like committee
    # votes, amendments that are different from Amendments_In_Context
    # or Floor_Amendments, etc. For now, just take the ones that map
    # to plain bill numbers, which are the original bill text in html/pdf.
    for dirtype in dirs_by_chamber:
        for chamber in chambers:
            listingurl = posixpath.join(baseurl, dirtype, chamber)
            nonexistent = set()
            dirlist = billrequests.get_html_dirlist(listingurl)

            for l in dirlist:
                billno = None

                filename = l['name']

                # The actual bill content is in files like SB0258.HTML;
                # names like SB0258IC1.HTML are likely amendments.
                try:
                    m = bill_file_pat.search(filename)
                    if m:
                        billno = m.group(1) + m.group(2)
                except Exception as e:
                    print("Exception trying to match bill_file_pat:",
                          filename, e, file=sys.stderr)

                if billno:
                    # It's bill original content

                    # Sometimes there are links that are just wrong.
                    # For instance, /Sessions/23%20Regular/bills/house/
                    # includes a link HB0005.HTML (and .PDF)
                    # but there is no HB5 in 2023, and the contents of
                    # HB0005.HTML/PDF are actually for SB5.
                    if billno not in g_allbills[yearcode]:
                        nonexistent.add(billno)
                        continue

                    href = l['url']
                    hrefl = href.lower()

                    if hrefl.endswith(".html"):
                        g_allbills[yearcode][billno]["contents"] = href
                    elif hrefl.endswith(".pdf"):
                        g_allbills[yearcode][billno]["pdf"] = href
                    else:
                        print("Not sure what to do with file type", href,
                              file=sys.stderr)

                else:
                    # It's not the main content for a billno, but it might
                    # be an amendment or committee sub since those are
                    # in the same directory with names like SB0520COS.pdf
                    # XXX Many of those files aren't actually amendments,
                    # though, but instead reports of passage. Even when
                    # they are amendments, they're floor amendents from
                    # committee and may not have been adopted.
                    # Better to leave them out, for now.
                    # billno = get_billno_from_filename(filename)
                    # if billno:
                    #     if billno not in g_allbills[yearcode]:
                    #         print("Found possible committee sub", filename,
                    #               "for as yet nonexistent bill", billno,
                    #               file=sys.stderr)
                    #         nonexistent.add(billno)
                    #     else:
                    #         if "amend" not in g_allbills[yearcode][billno]:
                    #             g_allbills[yearcode][billno]["amend"] = []
                    #         if l['url'] not in \
                    #            g_allbills[yearcode][billno]['amend']:
                    #             g_allbills[yearcode][billno]['amend'].append(
                    #                 l['url'])
                    # else:
                    #     print(filename, "is neither a bill nor comm sub",
                    #           file=sys.stderr)

                    # print("Skipping possible committee sub", filename,
                    #       "for", billno)
                    continue

            if nonexistent:
                print("Nonexistent bills", ', '.join(nonexistent),
                      "reffed in", listingurl, file=sys.stderr)

    # Special treatment for tabled bills
    listingurl = posixpath.join(baseurl, "Tabled_Reports")
    dirlist = billrequests.get_html_dirlist(listingurl)
    nonexistent = set()
    for l in dirlist:
        filename = l['name']   # These are names like 'HB0060CP1T.pdf'
        billno = get_billno_from_filename(filename)
        if billno not in g_allbills[yearcode]:
            nonexistent.add(billno)
            continue
        g_allbills[yearcode][billno]["tabled"] = True
    if nonexistent:
        print("Nonexistent tabled bills", ', '.join(nonexistent),
              "reffed in", listingurl, file=sys.stderr)

    # Don't save the file; assume we're called from update_allbills()
    # which will save the JSON.
    return g_allbills


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

    # Ideally, everything else -- norably bill list and meeting datetime --
    # will come from the PDF parser, since the PDF agendas are kept
    # much more up to date than the PDF page.
    # However, some bills on the PDF pages are sometimes unparseable,
    # while the HTML is much more tractable. So this will get initial
    # lists which may be modified from the PDF later.

    # The floorurl pages (below) don't say anything about the meeting date.
    # But the next meeting's date is encoded into the Floor Calendar PDF
    # links on the Session Calendar overview page:
    calendars_url = "https://www.nmlegis.gov/Calendar/Session"
    if cache_locally:
        soup = billrequests.soup_from_cache_or_net(calendars_url)
    else:
        r = billrequests.get(url)
        soup = BeautifulSoup(r.text, 'lxml')

    def get_date_from_floor_link(chamber, soup):
        """chamber is "House" or "Senate. Return pdf_url, yyyy-mm-dd"""
        href = None
        try:
            floorlink = soup.find('a', {
                "id": "MainContent_dataList%sCalendarFloor_linkFloorCalendar_0"
                       % chamber
            })
            href = 'https://www.nmlegis.gov' + floorlink.get('href')
            # href="/Agendas/Floor/hFloor021222.pdf?t=637803128677866884"
            floorlinkpat = r".*/Floor/%sFloor([0-9]{6})\.pdf.*" \
                % chamber[0].lower()
            m = re.match(floorlinkpat, href)
            mmddyy = m.group(1)
            return href, \
                '20%s-%s-%s' % (mmddyy[4:], mmddyy[2:4], mmddyy[:2])
        except:
            print("Couldn't get floor PDF link", file=sys.stderr)
            return href, 0

    # Some fields that, for committees, are picked up by parsing the
    # PDF agendas. But the house/senate PDF agendas don't reliably list time.
    pdf_url, yyyymmdd = get_date_from_floor_link(code, soup)
    ret['meetings'] = [ {
        'datetime': yyyymmdd,
        'url': pdf_url,
        'zoom': 'https://sg001-harmony.sliq.net/00293/harmony',
        'bills': []
    } ]

    # Now we're done with the calendars URL.
    # The bills come from the HTML Floor_Calendar page.
    floorurl = "https://www.nmlegis.gov/Entity/%s/Floor_Calendar" % code
    if cache_locally:
        soup = billrequests.soup_from_cache_or_net(floorurl)
    else:
        r = billrequests.get(url)
        soup = BeautifulSoup(r.text, 'lxml')

    # House and Senate meeting times aren't listed on their schedule pages --
    # you just have to know. Both of them can meet at any time of day;
    # in 2021, 11am is a common Senate meeting time, 2pm is common for
    # the House and the House almost never meets before noon, but the
    # times given here are just a wild guess, and instead of showing
    # exact times to the user, we'll show a link to the only official
    # meeting time, the one on the PDF schedules. Even that is just an
    # early boundary, since they often meet as much as several hours late.
    for a in soup.find_all('a', { "id": house_senate_billno_pat }):
        ret['meetings'][0]['bills'].append(a.text.replace(' ', '')
                                            .replace('*', ''))
    return ret


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
        for row in membertbl.find_all('tr'):
            cells = row.find_all('td')
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


def parse_date_time(dts):
    """Parse a datetime string in ISO format, except that it may
       or may not include a time.
    """
    if 'T' in dts:
        return datetime.datetime.strptime(dts, "%Y-%m-%dT%H:%M:%S")

    # There may or may not be a time; if there wasn't,
    # parse only the date portion. H and M will be zero.
    else:
        return datetime.datetime.strptime(dts, "%Y-%m-%d")


def expand_timestr(meeting):
    # Add more to the the free-form "timestr" field.

    # Start with a nice human-friendly date
    if "time" in meeting and meeting["time"]:
        meeting["timestr"] = meeting["time"]
    elif "datetime" in meeting:
        if meeting["datetime"].hour:
            meeting["timestr"] = meeting["datetime"].strftime("%a, %b %d %I:%M %p")
        else:
            meeting["timestr"] = meeting["datetime"].strftime("%a, %b %d ")
    else:
        meeting["timestr"] = ""

    # then add the human-readable, but maybe unparseable, time.
    # For each item, check to see whether it's already
    # been added from an earlier meeting of the same committee.
    if 'room' in meeting:
        meeting["timestr"] += ", room: %s" \
            % meeting['room']
    if 'zoom' in meeting and 'zoom link' not in meeting["timestr"].lower():
        meeting["timestr"] \
            += ", <a href='%s' target='_blank'>zoom link</a>" \
               % meeting['zoom']
    # Make sure all meetings have the sliq link
    if 'harmony.sliq.net' not in meeting["timestr"]:
        meeting["timestr"] \
            += ", <a href='https://sg001-harmony.sliq.net/00293/harmony'" \
               " target='_blank'>watch on sliq</a>"
    if 'url' in meeting and 'PDF schedule' not in meeting["timestr"]:
        meeting["timestr"] \
            += ", <a href='%s' target='_blank'>PDF schedule</a>" \
               % meeting['url']


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
        jsonsrc = "https://nmlegis.edsantiago.com/schedule.json"

    # Version for the JSON schema, to tell whether something
    # might have changed
    JSONSCHEMA = "20230124"

    # XXX Eventually should check to make sure it's being kept
    # up to date and at least some dates are in the future.
    # h = requests.get(pdf_cal_url).headers["Last-Modified"]
    # is something like "Sun, 06 Feb 2022 21:55:07 GMT"
    # the strftime format is "%a, %d %b %Y %H:%M:%S GMT"
    # but billrequests doesn't yet handle head() properly.
    if jsonsrc.startswith("http") and ':' in jsonsrc:
        r = billrequests.get(jsonsrc)
        scheduledata = r.json()
    else:
        with open(jsonsrc) as jfp:
            scheduledata = json.load(jfp)

    if scheduledata["_schema"] != JSONSCHEMA:
        # Temporary handler for the previous schema:
        if scheduledata["_schema"] == "20220213":
            print("*********** Using old JSON schema", file=sys.stderr)
            return expand_committees_20220213(scheduledata)

        print("*****************************************\n"
              "**** NEW SCHEMA ON scheduledata.json ****",
              scheduledata["_schema"], file=sys.stderr)
        return None

    committees = {}

    for mtgdate in scheduledata:
        if mtgdate[0] == '_':
            continue
        for mtgtime in scheduledata[mtgdate]:
            for commcode in scheduledata[mtgdate][mtgtime]:
                # This is a dict with bills, date, datetime,
                # mtime, name, room, time, url.
                meeting = scheduledata[mtgdate][mtgtime][commcode]

                if commcode not in committees:
                    commdict = expand_committee(commcode)
                    # This gives code, name, chair, members
                    if not commdict:
                        print("Couldn't expand committee",
                              commdict, file=sys.stderr)
                        continue

                    committees[commcode] = commdict
                    committees[commcode]["meetings"] = []

                # Convert datetime into the Python object
                if "datetime" in meeting:
                    try:
                        meeting["datetime"] = parse_date_time(meeting["datetime"])
                    except Exception as e1:
                        # One error we've seen is "datetime": "T11:00:00"
                        # so try looking for that
                        if meeting["datetime"][0] == 'T':
                            dts = meeting["date"] + meeting["datetime"]
                            try:
                                meeting["datetime"] = parse_date_time(dts)
                            except Exception as e2:
                                print("Can't parse datetime:", e2,
                                      meeting["datetime"],
                                      file=sys.stderr)
                                del meeting["datetime"]

                if "datetime" not in meeting:
                    # either there was no datetime to begin with,
                    # or it was unparseable -- for example, 'T11:00:00'
                    # Try to get it from the date and time
                    if 'date' in meeting:
                        if 'time' in meeting:
                            meeting["datetime"] = parse_date_time(
                                meeting["date"], meeting["time"])
                        else:
                            meeting["datetime"] = parse_date_time(
                                meeting["date"], None)

                # Some committees have "time" field set to something like
                # "After the Floor Session", which typically means
                # 1pm or so. Set those to 11:00 so they don't sort
                # before morning meetings.
                if 'time' not in meeting:
                    print("No 'time' in", commcode, "meeting:", meeting,
                          file=sys.stderr)
                elif (meeting["datetime"].hour == 0 and
                    meeting["time"].lower().startswith("after")):
                    meeting["datetime"] = \
                        meeting["datetime"].replace(hour=11)

                expand_timestr(meeting)

                committees[commcode]["meetings"].append(meeting)

    # pprint(committees)
    return committees


def expand_committees_20220213(scheduledata):
    print("Parsing the old 20220213 JSON schema", file=sys.stderr)
    committees = {}
    for commcode in scheduledata:
        if commcode == "_schema":
            if scheduledata["_schema"] != "20220213":
                print("*****************************************\n"
                      "**** NEW SCHEMA ON scheduledata.json ****",
                      scheduledata["_schema"], file=sys.stderr)
            continue

        commdict = expand_committee(commcode)
        if not commdict:
            print("Couldn't expand committee", commdict, file=sys.stderr)
            continue
        committees[commcode] = commdict
        # Now committees[commcode] has everything except meeting times.

        if "meetings" not in committees[commcode]:
            committees[commcode]["meetings"] = []

        for meetingdate in scheduledata[commcode]:
            for pdfmtg in scheduledata[commcode][meetingdate]:
                # Are there bills? If no, don't care about this meeting
                if "bills" not in pdfmtg:
                    continue

                if "meetings" in committees[commcode] and \
                   len(committees[commcode]["meetings"]) >= 1:
                    meeting = committees[commcode]["meetings"][0]
                else:
                    meeting = {}

                # meeting["timestr"] is a human-readable time (no date)
                # that doesn't need to be parseable,
                # e.g. it might be "9:30" but it also might be
                # "1:30 or half an hour after floor session".
                if "time" in pdfmtg:
                    meeting["timestr"] = pdfmtg["time"]
                elif "timestr" not in meeting:
                    meeting["timestr"] = ""

                # Parse datetime field, which is in ISO format
                # but may be date only or date and time.
                # Replace datetime or date field.
                try:
                    if 'T' in pdfmtg["datetime"]:
                        meeting["datetime"] = datetime.datetime.strptime(
                            pdfmtg["datetime"], "%Y-%m-%dT%H:%M:%S")
                        if not meeting["timestr"]:
                            meeting["timestr"] \
                                = meeting["datetime"].strftime("%H:%M")
                    # There may or may not be a time; if there wasn't,
                    # parse only the date portion. H and M will be zero.
                    else:
                        meeting["datetime"] = datetime.datetime.strptime(
                            pdfmtg["datetime"], "%Y-%m-%d")

                except KeyError:
                    # No datetime, fall back on date
                    if "date" not in pdfmtg:
                        print("EEK! No 'date' field in", pdfmtg,
                              file=sys.stderr)
                        continue
                    meeting["datetime"] = datetime.datetime.strptime(
                        pdfmtg["date"], "%Y-%m-%d")

                except ValueError:
                    # probably bad datetime string, e.g. "2023-01-17T24:00:00"
                    print("Problem parsing date string", meeting["datetime"],
                          file=sys.stderr)

                except Exception:
                    print("Couldn't parse meeting datetime from",
                          scheduledata[commcode], file=sys.stderr)
                    continue

                # Now there's a datetime. Are there bills?
                # If there's a bill list already from expand_house_or_senate,
                # keep those and add in the new ones.
                if "bills" in pdfmtg and pdfmtg["bills"]:
                    if "bills" in meeting and meeting["bills"]:
                        meeting["bills"] \
                            = list(set(meeting["bills"]).union(pdfmtg["bills"]))
                    else:
                        meeting["bills"] = pdfmtg["bills"]
                if "bills" not in meeting or not meeting["bills"]:
                    print(commcode, ": No bills for meeting",
                          scheduledata[commcode], file=sys.stderr)
                    continue

                # Add more to the the free-form "timestr" field.

                # Start with a nice human-friendly date
                # meeting["time"] = meeting["datetime"].strftime("%a, %b %d ")
                # then add the human-readable, but maybe unparseable, time.
                # For each item, check to see whether it's already
                # been added from an earlier meeting of the same committee.
                if 'room' in pdfmtg and 'room:' not in meeting["timestr"]:
                    meeting["timestr"] += ", room: %s" \
                        % pdfmtg['room']
                if 'zoom' in pdfmtg and 'zoom link' not in meeting["timestr"]:
                    meeting["timestr"] \
                        += ", <a href='%s' target='_blank'>zoom link</a>" \
                           % pdfmtg['zoom']
                elif commcode == "House" or commcode == "Senate" \
                     and 'harmony.sliq.net' not in meeting["timestr"]:
                    meeting["timestr"] \
                        += ", <a href='https://sg001-harmony.sliq.net/00293/" \
                           "harmony' target='_blank'>watch on sliq</a>"
                if 'url' in pdfmtg and 'PDF schedule' not in meeting["timestr"]:
                    meeting["timestr"] \
                        += ", <a href='%s' target='_blank'>PDF schedule</a>" \
                           % pdfmtg['url']

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
    for opt in select.find_all('option'):
        value = opt.get('value')
        if value == "...":
            continue
        legs[value] = opt.text
    return legs


def get_legislator_list():
    """Returns a list of dictionaries with these fields:
       "firstname", "lastname", "title", "street", "city", "state", "zip",
       "office_phone", "office", "work_phone", "home_phone", "email"
       plus some extra fields that don't mirror the Legislator object.
    """
    legdata = None
    try:
        r = billrequests.get('https://nmlegis.edsantiago.com/legislators.json')
        if r.status_code == 200 and 'Last-Modified' in r.headers:
            # The last-modified date only changes when some
            # legislator's data changes. Make sure the file
            # isn't orphaned, has been updated this session:
            print("Fetched legislators.json", file=sys.stderr)
            print("last mod header is", r.headers['Last-Modified'])
            lastmod = datetime.datetime.strptime(r.headers['Last-Modified'],
                                   '%a, %d %b %Y %X %Z')
            print("lastmod:", lastmod)
            if ((datetime.datetime.now() - lastmod).days
                < 120):
                legdata = r.json()
            else:
                print("legislators.json is too old", lastmod,
                      file=sys.stderr)
        else:
            print("Didn't fetch legislators.json", file=sys.stderr)
            print("Status:", r.status_code, ", headers:", r.headers,
                  file=sys.stderr)
    except Exception as e:
        print("get_legislator_list(): exception", e, file=sys.stderr)

    if not legdata or 'H' not in legdata or 'S' not in legdata:
        print("Falling back to XLS: json was", legdata)
        return get_legislator_list_from_XLS()

    # Okay, we're using legislators.json.
    legislators = []
    for chamber in ('H', 'S'):
        for leg in legdata[chamber]:
            # First entry is a null
            if not leg:
                continue
            # Reconcile differences between legislators.json
            # and the Legislator class in models.py, and make sure
            # to remove leg['id'] since it freaks out sqlalchemy
            leg['sponcode'] = leg.pop('id')
            leg['work_phone'] = leg.pop('phone')
            leg['home_phone'] = ''
            legislators.append(leg)

            # legislators.json doesn't have title
            if chamber == 'H':
                leg['title'] = 'Representative'
            else:
                leg['title'] = 'Senator'

    return legislators


def get_legislator_list_from_XLS():
    """Fetches Legislators.XLS from the legislative website,
       returning the same fields as for get_legislator_list().
       Returns a list of dictionaries with these fields:
       "firstname", "lastname", "title", "street", "city", "state", "zip",
       "office_phone", "office", "work_phone", "home_phone", "email".
       Only needed if Ed's JSON isn't there.
    """
    houseurl = 'https://www.nmlegis.gov/Members/Legislator_List?T=R'
    senateurl = 'https://www.nmlegis.gov/Members/Legislator_List?T=S'
    house_sponcodes = get_sponcodes(houseurl)
    senate_sponcodes = get_sponcodes(senateurl)

    cachefile = '%s/%s' % (billrequests.CACHEDIR, 'Legislators.XLS')

    # The legislator XLS file is no longer on an ftp server, but in the
    # directory for the current session, e.g.
    # https://www.nmlegis.gov/Sessions/23%20Regular/Legislator%20Information/Legislators.XLS
    # No yearcode is passed in, so just fetch the one for this year.
    # XXX This only picks up the one from this year's regular session.
    # If there are any changes in special sessions, this won't get it.
    year2digit = datetime.date.today().strftime("%y")
    legurl = "https://www.nmlegis.gov/Sessions/%s%%20Regular/Legislator%%20Information/Legislators.XLS" % (year2digit)
    try:
        r = billrequests.get(legurl)
        if r.status_code == 200:
            cachefile = '%s/%s' % (billrequests.CACHEDIR, 'Legislators.XLS')
            with open(cachefile, "wb") as fp:
                fp.write(r.content)
            print("Successfully updated from Legislators.XLS", file=sys.stderr)
    except:
        print("Couldn't fetch", legurl, file=sys.stderr)
        return None

    # xlrd gives
    # WARNING *** OLE2 inconsistency: SSCS size is 0 but SSAT size is non-zero
    # but still seems to work okay.
    # However, it understandably won't work when ftp fetches a zero-length file.
    try:
        wb = xlrd.open_workbook(cachefile)
        sheet = wb.sheet_by_name(wb.sheet_names()[0])
        if not sheet or sheet.ncols <= 0 :
            print("Null sheet, couldn't read", cachefile, file=sys.stderr)
            return None
    except Exception as e:
        print("Couldn't read XLS file", cachefile, ": error was", e,
              file=sys.stderr)
        return None

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

        def find_sponcode(leg, remove_accents=False):
            sponcode = None
            if leg['title'].startswith('Rep'):
                for sp in house_sponcodes:
                    if fullname == house_sponcodes[sp]:
                        return sp
            elif leg['title'].startswith('Sen'):
                for sp in senate_sponcodes:
                    if fullname == senate_sponcodes[sp]:
                        return sp

        sponcode = find_sponcode(leg)

        # If nothing matched, maybe there's an accented character that's
        # done differently in Legislator_List vs. Legislators.XLS,
        # like Eleanor Chavez/Eleanor Chávez
        if not sponcode:
            sponcode = find_sponcode(leg, remove_accents=True)

        if sponcode:
            # print("%s: %s" % (sp, fullname))
            leg['sponcode'] = sponcode
            legislators.append(leg)
        else:
            print("**** %s has no sponcode in Legislator_List" % fullname,
                  file=sys.stderr)

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
