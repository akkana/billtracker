#!/usr/bin/env python3

# Scrape bill data from bill pages from nmlegis.org.

import datetime
import re
import requests
import urllib.parse
import posixpath
from bs4 import BeautifulSoup

# For offline debugging without hitting the real nmlegis site too often,
# URL handling goes through this class, which can be set to debug mode.
# For debugging, set:
# nmlegisbill.url_mapper = nmlegisbill.LocalURLmapper('https://www.nmlegis.gov')
# nmlegisbill.url_mapper = \
#     nmlegisbill.LocalhostURLmapper('http://localhost/billtracker',
#                                    'https://www.nmlegis.gov')
# or define your own URL mapper class: see DebugURLMapper below.

class URLmapper:
    def __init__(self, baseurl, billurlpat):
        '''baseurl is the basic top-level home page (no terminal slash).
           billurlpat is the URL pattern for bills, taking five arguments:
           baseurl, chamber, billtype, number and (2-digit string) year.
           If you need something that doesn't include these four
           patterns in that order, redefine bill_url() accordingly.
        '''
        self.baseurl = baseurl
        self.billurlpat = billurlpat

    def to_abs_link(self, url, cururl):
        '''Try to map relative and / URLs to absolute ones.
           cururl is the page on which the link was found,
           for relative links like ../
        '''
        purl = urllib.parse.urlparse(url)
        if purl.scheme:
            return url

        if purl.path.startswith('/'):
            return self.baseurl + url

        # Otherwise it's (we hope) a relative URL, relative to cururl.
        curl = urllib.parse.urlparse(cururl)
        path = posixpath.normpath(posixpath.join(posixpath.dirname(curl.path),
                                                 purl.path))
        url = curl.scheme  + '://' + curl.netloc + path
        if purl.query:
            url += '?' + purl.query
        return url

    def bill_url(self, chamber, billtype, number, year):
        return self.billurlpat % (self.baseurl, chamber, billtype, number,
                                  (year_to_2digit(year)))

#
# Two derived classes that are useful for debugging:
#

# Use localhost:// with cached files, for testing CGI:
class LocalhostURLmapper(URLmapper):
    def __init__(self, localurl, realurl):
        self.localurl = localurl
        self.baseurl = realurl

    def bill_url(self, chamber, billtype, number, year):
        # print('Local url is %s/test/20%s-%s%s%s.html' % (self.localurl,
        #                                                  year_to_2digit(year),
        #                                                  chamber, billtype,
        #                                                  number))
        return '%s/test/20%s-%s%s%s.html' % (self.localurl,
                                             year_to_2digit(year),
                                             chamber, billtype, number)

# Use cached local files: good for unit tests.
class LocalURLmapper(URLmapper):
    '''For debugging, look for files like ./test/2018-HJR1.html
       but still use the real links for other links.
    '''
    def __init__(self, baseurl):
        self.baseurl = baseurl

    def bill_url(self, chamber, billtype, number, year):
        return './test/20%s-%s%s%s.html' % (year_to_2digit(year),
                                            chamber, billtype, number)

url_mapper = URLmapper('https://www.nmlegis.gov',
    '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')

def year_to_2digit(year):
    '''Translate a year in various formats to a 2-digit string.
    '''

    if type(year) is int:
        if year > 2000:
            year -= 2000
        return '%02d' % year

    elif type(year) is str:
        if len(year) > 2:
            return year[-2:]

    # Use this year if not defined or in an unknown format.
    return '%02d' % (datetime.datetime.now().year - 2000)

def billno_to_parts(billno, year=None):
    year = year_to_2digit(year)

    # billno is chamber, bill type, digits, e.g. HJM4. Parse that:
    match = re.match('([HS])([A-Z]+)([0-9]+)', billno)
    if not match:
        raise RuntimeError("Can't parse bill name '%s'" % billno)
    chamber, billtype, number = match.groups()
    return chamber, billtype, number, year

def parse_bill_page(billno, year=None):
    '''Download and parse a bill's page on nmlegis.org.
       Return a dictionary containing:
       chamber, billtype, number, year,
       title, sponsor, sponsorlink,
       curloc, curloclink, and contents_url.
    '''

    billdic = { 'billno': billno }
    (billdic['chamber'], billdic['billtype'],
     billdic['number'], billdic['year']) = billno_to_parts(billno, year)

    baseurl = url_mapper.bill_url(billdic['chamber'],
                                  billdic['billtype'],
                                  billdic['number'],
                                  billdic['year'])
    if ':' in baseurl:
        billdic['bill_url'] = baseurl
        r = requests.get(baseurl)
        soup = BeautifulSoup(r.text, 'lxml')
    else:
        with open(baseurl) as fp:
            billdic['bill_url'] = baseurl
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
        return None
    sponsor_a = soup.find("a",
                          id="MainContent_formViewLegislation_linkSponsor")
    billdic['sponsor'] = sponsor_a.text.strip()
    billdic['sponsorlink'] = url_mapper.to_abs_link(sponsor_a['href'], baseurl)

    curloc_a  = soup.find("a",
                          id="MainContent_formViewLegislation_linkLocation")
    billdic['curloc'] = curloc_a.text.strip()
    billdic['curloclink'] = url_mapper.to_abs_link(curloc_a['href'], baseurl)

    billdic['contents_url'] = url_mapper.to_abs_link(soup.find("a",
                                          id="MainContent_formViewLegislationTextIntroduced_linkLegislationTextIntroducedHTML")['href'],
                                           baseurl)

    # The bill's page has other useful info, like votes, analysis etc.
    # but unfortunately that's all filled in with JS and Ajax so
    # it's invisible to us.

    return billdic

if __name__ == '__main__':
    def print_bill_dic(bd):
        print("%s: %s" % (bd['billno'], bd['title']))
        print("Current location: %s --> %s" % (bd['curloc'],
                                               bd['curloclink']))
        print("Sponsor: %s --> %s" % (bd['sponsor'], bd['sponsorlink']))
        print("Contents at: %s" % (bd['contents_url']))

    billdic = parse_bill_page('HJR1')
    print_bill_dic(billdic)

