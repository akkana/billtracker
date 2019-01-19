#!/usr/bin/env python

from __future__ import print_function

from .billutils import URLmapper, year_to_2digit, billno_to_parts

# Scrape bill data from bill pages from nmlegis.org.

import sys, os
import datetime, dateutil.parser
import time
import re
import requests
import posixpath
from collections import OrderedDict
from bs4 import BeautifulSoup

url_mapper = URLmapper('https://www.nmlegis.gov',
    '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')

committees = {
    "HAFC": "House Appropriations & Finance",
    "HAWC": "House Agriculture, Water & Wildlife",
    "HAWR": "Agriculture, Water Resources",
    "HBEC": "House Business & Employment",
    "HBIC": "House Business &amp; Industry",
    "HCAL": "House Calendar (for a vote)",
    "HCPAC": "Consumer &amp; Public Affairs",
    "HEC": "House Education Committee",
    "HEENC": "House Energy, Environment & Natural Resources",
    "HGEIC": "House Gov't, Elections & Indian Affairs",
    "HHC": "House Health",
    "HHHC": "House Health and Human Services",
    "HJC": "House Judiciary",
    "HLEDC": "House Labor &amp; Economic Development",
    "HLELC": " House Local Government, Elections, Land Grants &amp; Cultural Affairs",
    "HR": "House Rules",
    "HXRC": "House Rules & Order of Business Committee",
    "HRPA": "House Regulatory & Public Affairs",
    "HSCA": "House Safety & Civil Affairs",
    "HSIVC": "House  State Gov't, Indian &amp; Veteran Affairs",
    "HTPWC": "House Transportation, Public Works &amp; Capital Improvements",
    "HTPW": "House Transportation & Public Works",
    "HTRC": "House Tax &amp; Revenue",
    "HWMC": "House Ways & Means",
    "SAIC": "Senate Indian and Cultural Affairs",
    "SCAL": "Senate Calendar (for vote)",
    "SXCC": "Senate Committee on Committees",
    "SCON": "Senate Conservation",
    "SCORC": "Senate Corporations & Transportation",
    "SEC": "Senate Education Committee",
    "SFC": "Senate Finance Committee",
    "SJC": "Senate Judiciary Committee",
    "SPAC": "Senate Public Affairs",
    "SRC": "Senate Rules Committee",
}

# User-friendly strings for the various bill keys:
# (Not actually used yet)
# keytitles = {
#     'billno'       : 'Bill #',
#     'chamber'      : 'Chamber',
#     'billtype'     : 'Type',
#     'number'       : 'Number',
#     'year'         : 'Year',
#     'bill_url    ' : 'Bill Link',
#     'title'        : 'Title',
#     'sponsor'      : 'Sponsor',
#     'sponsorlink'  : 'Sponsor link',
#     'curloc'       : 'Current Location',
#     'curloclink'   : 'Current Location Link',
# }

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
        '%s/Sessions/%s%%20Regular/firs/%s%s00%s.PDF' \
        % (url_mapper.baseurl, year, chamber, billtype, number),
        None)
    lesclink = url_mapper.to_local_link(
        '%s/Sessions/%s%%20Regular/LESCAnalysis/%s%s00%s.PDF' \
               % (url_mapper.baseurl, year, chamber, billtype, number),
        None)
    amendlink = url_mapper.to_local_link(
        '%s/Sessions/%s%%20Regular/Amendments_In_Context/%s%s00%s.PDF' \
               % (url_mapper.baseurl, year, chamber, billtype, number),
        None)

    if ':' in firlink:
        request = requests.get(firlink)
        if request.status_code != 200:
            firlink = None
    else:
        firlink = None
    if ':' in lesclink:
        request = requests.get(lesclink)
        if request.status_code != 200:
            lesclink = None
    else:
        lesclink = None

    return firlink, lesclink, amendlink

def bill_url(billno):
    chamber, billtype, number, year = billno_to_parts(billno, year=None)

    return 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' % (chamber, billtype, number, year)

def parse_bill_page(billno, year=None, cache_locally=True):
    '''Download and parse a bill's page on nmlegis.org.
       Return a dictionary containing:
       chamber, billtype, number, year, title, sponsor, sponsorlink,
       curloc, curloclink.
       Set update_date to now.

       If cache_locally, will save downloaded files to local cache.
       Will try to read back from cache if the cache file isn't more
       than 2 hours old.

       Does *not* save the fetched bill back to the database.
    '''

    billdic = { 'billno': billno }
    (billdic['chamber'], billdic['billtype'],
     billdic['number'], billdic['year']) = billno_to_parts(billno, year)

    baseurl = url_mapper.bill_url(billdic['chamber'],
                                  billdic['billtype'],
                                  billdic['number'],
                                  billdic['year'])

    if cache_locally:
        cachedir = 'cache'
        if not os.path.exists(cachedir):
            try:
                os.mkdir(cachedir)
            except:
                print("Couldn't create cache dir", cachedir, "-- not caching")
                cache_locally = False

    if cache_locally:
        filename = os.path.join(cachedir,
                                '20%s-%s.html' % (billdic['year'], billno))

        # Use cached pages so as not to hit the server so often.
        if os.path.exists(filename):
            filestat = os.stat(filename)
            if (time.time() - filestat.st_mtime) < 2 * 60 * 60:
                print("Already cached:", billno, file=sys.stderr)
                baseurl = filename
            else:
                print("Re-fetching: cache has expired on", billno,
                      file=sys.stderr)

    if ':' in baseurl:
        # billdic['bill_url'] = url_mapper.to_abs_link(baseurl, baseurl)
        r = requests.get(baseurl)
        soup = BeautifulSoup(r.text, 'lxml')

        if cache_locally:
            # Python 3 these days is supposed to use the system default
            # encoding, I thought, but sometimes it doesn't and dies
            # trying to write to the cache file unless you specify
            # an encoding explicitly:
            with open(filename, "w", encoding="utf-8") as cachefp:
                # r.text is str and shouldn't need decoding
                cachefp.write(r.text)
                # cachefp.write(r.text.decode())
                print("Cached locally as %s" % filename, file=sys.stderr)
    else:
        with open(baseurl) as fp:
            # billdic['bill_url'] = baseurl
            soup = BeautifulSoup(fp, 'lxml')

        # This probably ought to be folded into the url mapper somehow.
        baseurl = "http://www.nmlegis.gov/Legislation/Legislation"

    # If something failed -- for instance, if we got an empty file
    # or an error page -- then the title span won't be there.
    # Detect that:
    try:
        billdic['title'] = soup.find("span",
                                     id="MainContent_formViewLegislation_lblTitle").text
    except AttributeError:
        # If we cached, remove the cache file.
        if cache_locally and filename:
            os.unlink(filename)
        print("No such bill %s" % billno)
        return None
    sponsor_a = soup.find("a",
                          id="MainContent_formViewLegislation_linkSponsor")
    billdic['sponsor'] = sponsor_a.text.strip()
    billdic['sponsorlink'] = url_mapper.to_abs_link(sponsor_a.get('href'),
                                                    baseurl)

    curloc_a  = soup.find("a",
                          id="MainContent_formViewLegislation_linkLocation")
    billdic['curloc'] = curloc_a.text.strip()
    billdic['curloclink'] = url_mapper.to_abs_link(curloc_a.get('href'),
                                                   baseurl)

    contents_a = soup.find("a",
                           id="MainContent_formViewLegislationTextIntroduced_linkLegislationTextIntroducedHTML")
    # billdic['contents_url'] = url_mapper.to_abs_link(contents_a.get('href'),
    #                                                  baseurl)

    # Does the bill have any amendments?
    # Unfortunately we can't get the amendments themselves --
    # they're only available in PDF. But we can see if they exist.
    # amenddiv = soup.find("div", id="MainContent_tabContainerLegislation_tabPanelFloorReports")
    #     # Inside this div is a div for a label (Proposed, Adopted, Not Adopted)
    #     # followed by a table where (I think) there's a <tr><td> for each
    #     # amendment in that class; the actual amendment will look like
    #     # <a ... href="/Sessions/18%20Regular/memorials/house/HJM010FH1.pdf">
    #     #   <span ...>House Floor Amendment 1</span> &nbsp;
    #     #   <span ...">2/07/18</span>
    #     # </a>

    # Alternately, the "Amendments in Context" button:
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

# There doesn't seem to be a way, without javascript,
# to get a list of all current legislation. Sigh.
# Here's a failed attempt.
# def get_all_legislation(year):
#     payload = {'ctl00$MainContent$ddlSessionStart': '56',
#                'ctl00$MainContent$ddlSessionEnd': '56',
#                'ctl00$MainContent$chkSearchBills': 'on',
#                'ctl00$MainContent$chkSearchMemorials': 'on',
#                'MainContent_chkSearchResolutions': 'on',
#               }
#     r = requests.post('https://nmlegis.gov/Legislation/Legislation_List',
#                       data=payload)

def contents_url(billno):
    if billno.startswith('S'):
        chamber = 'senate'
    else:
        chamber = 'house'
    return 'https://www.nmlegis.gov/Sessions/19%%20Regular/bills/%s/%s.html' \
        % (chamber, billno)

if __name__ == '__main__':
    def print_bill_dic(bd):
        print("%s: %s" % (bd['billno'], bd['title']))
        print("Current location: %s --> %s" % (bd['curloc'],
                                               bd['curloclink']))
        print("Sponsor: %s --> %s" % (bd['sponsor'], bd['sponsorlink']))
        print("Contents at: %s" % (contents_url(bd['billno'])))

    billdic = parse_bill_page('HJR1')
    print_bill_dic(billdic)

def user_bill_summary(user):
    '''user is a dictionary. Examine each of user's bills,
       see if it looks like it's changed since user's last check.
       Return summary strings in html and plaintext formats (in that
       order) showing which bills have changed and which haven't.
    '''
    # How recently has this user updated?
    last_check = user['last_check']
    print("Last check for %s is"% user['email'], last_check)

    # Set up the strings we'll return.
    # Keep bills that have changed separate from bills that haven't.
    newertext = '''Bills that have changed since %s's\n      last check at %s:''' \
               % (user['email'], last_check.strftime('%m/%d/%Y %H:%M'))
    oldertext = '''Bills that haven't changed:'''
    newerhtml = '''<html>
<head>
<style type="text/css">
  body { background: white; }
  div.odd { background: #ffe; padding: 15px; }
  div.even { background: #efe; padding: 15px; }
</style>
</head>
<body>
<h2>%s</h2>''' % newertext
    olderhtml = '<h2>%s</h2>' % oldertext

    # Get the user's list of bills:
    sep = re.compile('[,\s]+')
    userbills = sep.split(user['bills'])

    # For each bill, get the mod_date and see if it's newer:
    even = True
    for billno in userbills:
        billdic = fetch_bill(billno)

        # Make a string indicating the last action and also when the
        # website was updated, which might be significantly later.
        action_datestr = ''
        if billdic['last_action_date']:
            action_datestr = "last action " \
                             + billdic['last_action_date'].strftime('%m/%d/%Y')

        if billdic['mod_date']:
            if action_datestr:
                action_datestr += ", "
            action_datestr += "updated " \
                             + billdic['mod_date'].strftime('%m/%d/%Y')

        if billdic['mod_date'] and billdic['mod_date'] >= last_check:
            # or billdic['mod_date'] >= last_check
            # ... if I ever get mod_date working right
            analysisText = ''
            analysisHTML = ''
            if billdic['amendlink']:
                analysisText += '\n   Amendments: ' + billdic['amendlink']
                analysisHTML += '<a href="%s">Amendments</a>' \
                                % billdic['amendlink']
            if billdic['FIRlink']:
                analysisText += '\n   FIR: ' + billdic['FIRlink']
                analysisHTML += '<a href="%s">FIR report</a>' \
                                % billdic['FIRlink']
            if billdic['LESClink']:
                analysisText += '\n   LESC: ' + billdic['LESClink']
                analysisHTML += '<a href="%s">LESC report</a>' \
                                % billdic['LESClink']
            if analysisHTML:
                analysisHTML += '<br />'

            even = not even
            newertext += '''\n
%s %s
  (%s)
  Bill page: %s
  Current location: %s %s
  Bill text: %s
  Analysis: %s
  Status:
%s''' % (billno, billdic['title'], action_datestr,
         bill_url(billno),
         billdic['curloc'], billdic['curloclink'],
         contents_url(billno), analysisText, billdic['statustext'])
            newerhtml += '''
<div class="%s">
<a href="%s">%s: %s</a> .. updated %s<br />
  Current location: <a href="%s">%s</a><br />
  <a href="%s">Text of bill</a><br />
  %s
  Status:
%s
</div>''' % ("even" if even else "odd",
             bill_url(billno), billno, billdic['title'],
             action_datestr, billdic['curloc'], billdic['curloclink'],
             contents_url(billno), analysisHTML, billdic['statusHTML'])

        else:
            oldertext += "\n%s %s (%s)" % (billno,
                                           billdic['title'],
                                           action_datestr)
            olderhtml += '<br /><a href="%s">%s %s</a> .. %s' % \
                        (bill_url(billno), billno, billdic['title'],
                         action_datestr)

    return (newerhtml + olderhtml + '</body></html>',
            '===== ' + newertext + "\n\n===== " + oldertext)

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


