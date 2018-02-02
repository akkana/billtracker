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

def parse_bill_page(billno, year=None):
    chamber, billtype, number, year = billno_to_parts(billno, year)

    bill_url = 'https://www.nmlegis.gov/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s' % (chamber, billtype, number, year)
    print("bill page:", bill_url)

    r = requests.get(bill_url)
    soup = BeautifulSoup(r.text, 'lxml')

    title = soup.find("span",
                      id="MainContent_formViewLegislation_lblTitle").text
    sponsor_a = soup.find("a",
                          id="MainContent_formViewLegislation_linkSponsor")
    sponsor = sponsor_a.text.strip()
    sponsorlink = nmlegis_link(sponsor_a['href'], bill_url)

    curloc_a  = soup.find("a",
                          id="MainContent_formViewLegislation_linkLocation")
    curloc = curloc_a.text.strip()
    curloclink = nmlegis_link(curloc_a['href'], bill_url)

    contents_url = nmlegis_link(soup.find("a",
                                          id="MainContent_formViewLegislationTextIntroduced_linkLegislationTextIntroducedHTML")['href'],
                                bill_url)

    # The bill's page has other useful info, like votes, analysis etc.
    # but unfortunately that's all filled in with JS and Ajax so
    # it's invisible to us.

    print("%s: %s" % (billno, title))
    print("Current location: %s --> %s" % (curloc, curloclink))
    print("Sponsor: %s --> %s" % (sponsor, sponsorlink))
    print("Contents at: %s" % (contents_url))

if __name__ == '__main__':
    parse_bill_page('SJM6')

