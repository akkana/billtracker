#!/usr/bin/env python3

# Scrape bill data from bill pages from nmlegis.org.

import datetime
import re
import requests
import urllib.parse
import posixpath
from bs4 import BeautifulSoup

def billno_to_parts(billno, year=None):
    # Turn year into a 2-digit string, like '18' for 2018
    if year:
        if type(year) is int:
            if year > 2000:
                year -= 2000
            year = '%02d' % year

        elif type(year) is str:
            if len(year) > 2:
                year = year[-2:]

    else:
        year = '%02d' % (datetime.datetime.now().year - 2000)

    # billno is chamber, bill type, digits, e.g. HJM4. Parse that:
    match = re.match('([HS])([A-Z]+)([0-9]+)', billno)
    if not match:
        raise RuntimeError("Can't parse bill name '%s'" % billno)
    chamber, billtype, number = match.groups()
    return chamber, billtype, number, year

def nmlegis_link(url, cururl):
    '''Try to map relative and / URLs to absolute ones.
    '''
    purl = urllib.parse.urlparse(url)
    if purl.scheme:
        return url

    if purl.path.startswith('/'):
        return 'https://www.nmlegis.gov' + url

    # Otherwise it's (we hope) a relative URL, relative to cururl.
    curl = urllib.parse.urlparse(cururl)
    path = posixpath.normpath(posixpath.join(posixpath.dirname(curl.path),
                                             purl.path))
    url = curl.scheme  + '://' + curl.netloc + path
    if purl.query:
        url += '?' + purl.query
    return url

def parse_bill_page(billno, year=None, localfile=None):
    '''Download and parse a bill's page on nmlegis.org.
       Optional localfile argument is only for unit tests.
       Return a dictionary containing:
       chamber, billtype, number, year,
       title, sponsor, sponsorlink,
       curloc, curloclink, and contents_url.
    '''

    billdic = { 'billno': billno }
    (billdic['chamber'], billdic['billtype'],
     billdic['number'], billdic['year']) = billno_to_parts(billno, year)

    baseurl = 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' % \
              (billdic['chamber'],
               billdic['billtype'],
               billdic['number'],
               billdic['year'])
    if localfile:
        with open(localfile) as fp:
            billdic['bill_url'] = localfile
            soup = BeautifulSoup(fp, 'lxml')
        baseurl = "http://www.nmlegis.gov/Legislation/Legislation"
    else:
        billdic['bill_url'] = baseurl
        r = requests.get(baseurl)
        soup = BeautifulSoup(r.text, 'lxml')

    billdic['title'] = soup.find("span",
                           id="MainContent_formViewLegislation_lblTitle").text
    sponsor_a = soup.find("a",
                          id="MainContent_formViewLegislation_linkSponsor")
    billdic['sponsor'] = sponsor_a.text.strip()
    billdic['sponsorlink'] = nmlegis_link(sponsor_a['href'], baseurl)

    curloc_a  = soup.find("a",
                          id="MainContent_formViewLegislation_linkLocation")
    billdic['curloc'] = curloc_a.text.strip()
    billdic['curloclink'] = nmlegis_link(curloc_a['href'], baseurl)

    billdic['contents_url'] = nmlegis_link(soup.find("a",
                                          id="MainContent_formViewLegislationTextIntroduced_linkLegislationTextIntroducedHTML")['href'],
                                           baseurl)

    # The bill's page has other useful info, like votes, analysis etc.
    # but unfortunately that's all filled in with JS and Ajax so
    # it's invisible to us.

    return billdic

if __name__ == '__main__':
    billdic = parse_bill_page('HJR1', localfile="test/2018-HJR1.html")

    print("%s: %s" % (billdic['billno'], billdic['title']))
    print("Current location: %s --> %s" % (billdic['curloc'],
                                           billdic['curloclink']))
    print("Sponsor: %s --> %s" % (billdic['sponsor'], billdic['sponsorlink']))
    print("Contents at: %s" % (billdic['contents_url']))
