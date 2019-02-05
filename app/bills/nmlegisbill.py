#!/usr/bin/env python3

from __future__ import print_function

from .billutils import URLmapper, year_to_2digit, billno_to_parts, \
      ftp_get, ftp_index

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


def bill_url(billno):
    chamber, billtype, number, year = billno_to_parts(billno, year=None)

    return 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' % (chamber, billtype, number, year)


cachedir = 'cache'

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
        cachefile = baseurl.replace('https://www.nmlegis.gov/', '').replace('/Legislation', '').replace('/', '_').replace('?', '_').replace('&', '_')
        cachefile = '%s/%s' % (cachedir, cachefile)

    # Use cached pages so as not to hit the server so often.
    if os.path.exists(cachefile):
        filestat = os.stat(cachefile)
        if (time.time() - filestat.st_mtime) < cachesecs:
            print("Already cached:", baseurl, file=sys.stderr)
            baseurl = cachefile

    if ':' in baseurl:
        print("Re-fetching: cache has expired on", baseurl, file=sys.stderr)

        # billdic['bill_url'] = url_mapper.to_abs_link(baseurl, baseurl)
        r = requests.get(baseurl)
        soup = BeautifulSoup(r.text, 'lxml')

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

def parse_bill_page(billno, year=None, cache_locally=True):
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

    # XXX number and year here are bogus
    baseurl = url_mapper.bill_url(billdic['chamber'],
                                  billdic['billtype'],
                                  billdic['number'],
                                  billdic['year'])

    if cache_locally:
        cachefile = os.path.join(cachedir,
                                 '20%s-%s.html' % (billdic['year'], billno))
        soup = soup_from_cache_or_net(baseurl, cachefile=cachefile,
                                      cachesecs=2*60*60)
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
        # If we cached, remove the cache file.
        if cache_locally and cachefile:
            os.unlink(cachefile)
        print("parse_bill_page: No such bill %s" % billno)
        return None

    sponsor_a = soup.find("a",
                          id="MainContent_formViewLegislation_linkSponsor")
    billdic['sponsor'] = sponsor_a.text.strip()
    billdic['sponsorlink'] = url_mapper.to_abs_link(sponsor_a.get('href'),
                                                    baseurl)

    curloc_a  = soup.find("a",
                          id="MainContent_formViewLegislation_linkLocation")
    curloc_href = curloc_a.get('href')
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

    # XXX What's the code for On Governor's Desk? Or Failed, or others?
    # XXX There's also a case where curloc_a is blank and curloc will
    # be something like "<b>Senate Intro</b> except with a lot of blanks
    # and newlines inside. Currently those show up as 'unknown':
    # I need to catch one in the act to test code to handle it,
    # and they don't stay in that state for long.

    else:
        billdic['curloc'] = ''

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
        billdic["statustext"] = actiontext

    # The bill's page has other useful info, like votes, analysis etc.
    # but unfortunately that's all filled in later with JS and Ajax so
    # it's invisible to us. But we can make a guess at FIR and LESC links:
    billdic['FIRlink'], billdic['LESClink'], billdic['amendlink'] \
        = check_analysis(billno)
    # print("Checked analysis:", billdic['FIRlink'], billdic['LESClink'],
    #       billdic['amendlink'], file=sys.stderr)

    billdic['update_date'] = datetime.datetime.now()
    billdic['mod_date'] = None

    return billdic

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

def all_bills():
    '''Return an OrderedDict of all bills, billno: [title, url]
    '''
    baseurl = 'https://www.nmlegis.gov/Legislation/'
    url = baseurl + 'Legislation_List?Session=57'
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'lxml')
    # with open('/home/akkana/src/billtracker/resources/Legislation_List?Session=57') as fp:
    #     t = fp.read()
    #     soup = BeautifulSoup(t, 'lxml')

    footable = soup.find('table', class_='footable')
    if not footable:
        print("Can't read the all-bills list", file=sys.stderr)
        return None

    allbills = OrderedDict()
    billno_pat = re.compile('MainContent_gridViewLegislation_linkBillID.*')
    title_pat = re.compile('MainContent_gridViewLegislation_lblTitle.*')
    for tr in footable.findAll('tr'):
        billno = tr.find('a', id=billno_pat)
        title = tr.find('span', id=title_pat)
        if billno and title:
            # Remove spaces and stars:
            allbills[billno.text.replace(' ', '').replace('*', '')] \
                = [ title.text, baseurl + billno['href'] ]

    return allbills

# Link lists from contents_url_for_parts
# A dictionary with keys of 'SB', 'HB', 'SJR' etc.
# each of whose contents are a dictionary of int billno: url.
Link_lists = {}

def contents_url_for_parts(chamber, billtype, number, year):
    '''A link to a page with a bill's contents in HTML.
       This alas cannot be inferred from the billno,
       because there is an unpredictable number of zeroes
       inserted in the middle: HR001, HM011, HM0111.
    '''
    chambertype = chamber + billtype    # e.g. HJR
    billnumint = int(number)

    try:
        return Link_lists[chambertype][billnumint]
    except:    # most likely KeyError, but why not catch everything?
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
    soup = soup_from_cache_or_net(url, cachesecs=12*60*60)
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

        Link_lists[chambertype][int(num)] = href

    # Hope we have it now!
    try:
        return Link_lists[chambertype][billnumint]
    except:
        pass
    return ''

def contents_url_for_billno(billno):
    '''A link to a page with a bill's contents in HTML,
       for bills not yet in the database.
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
