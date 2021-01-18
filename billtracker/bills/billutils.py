#!/usr/bin/env python3

import datetime
import posixpath
import re
import sys
from ftplib import FTP
import dateutil

if sys.version[:1] == '2':
    from urlparse import urlparse
else:
    from urllib.parse import urlparse


def year_to_2digit(year):
    '''Translate a year in various formats to the 2-digit string
       used on nmlegis, e.g. '19' rather than '2019' or 2019 or 19.
    '''
    if type(year) is int:
        if year > 2000:
            year -= 2000
        return '%02d' % year

    if type(year) is str:
        if len(year) > 2:
            return year[-2:]
        if len(year) == 1:
            return '0' + year
        return year

    # Use this year if not defined or in an unknown format.
    return '%02d' % (datetime.datetime.now().year - 2000)


def billno_to_parts(billno):
    '''Split a bill number into its parts: chamber, billtype, number
       Return chamber, billtype, number as strings
       suitable for an nmlegis URL.
    '''
    # billno is chamber, bill type, digits, e.g. HJM4. Parse that:
    match = re.match('([HS])([A-Z]+) *([0-9]+)', billno)
    if not match:
        raise RuntimeError("I don't understand bill number '%s'" % billno)
    chamber, billtype, number = match.groups()
    return chamber, billtype, number


#
# XXX These URL Mappers are flaky and may not be needed any more
# now that the unit tests use mocking. They should probably be removed.
#

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
        if not url:
            return url
        purl = urlparse(url)
        if purl.scheme:
            return url

        if purl.path.startswith('/'):
            return self.baseurl + url

        # Otherwise it's (we hope) a relative URL, relative to cururl.
        curl = urlparse(cururl)
        path = posixpath.normpath(posixpath.join(posixpath.dirname(curl.path),
                                                 purl.path))
        url = curl.scheme  + '://' + curl.netloc + path
        if purl.query:
            url += '?' + purl.query
        return url

    def to_local_link(self, url, cururl):
        '''In URLmappers that are local, return a local link
           that won't hit the server.
        '''
        return url

    def bill_url(self, chamber, billtype, number, year):
        return self.billurlpat % (self.baseurl, chamber, billtype, number,
                                  (year_to_2digit(year)))

#
# Two derived classes that are useful for debugging:
#

# Use localhost:// with cached files, for testing CGI:
class LocalhostURLmapper(URLmapper):
    def __init__(self, localurl, realurl, realbillurlpat):
        self.baseurl = localurl
        self.remoteurl = realurl
        self.realbillurlpat = realbillurlpat

    def to_local_link(self, url, cururl):
        '''In URLmappers that are local, return a local link
           that won't hit the server.
        '''
        if not url:
            return url
        return URLmapper.to_abs_link(self, url, cururl)
        # This should be an absolute link in terms of localhost.

    def to_abs_link(self, url, cururl):
        '''Try to map relative, / and localhost URLs to absolute ones
           based on the realurl.
           cururl is the page on which the link was found,
           for relative links like ../
        '''
        mapped_url = self.to_local_link(url, None)

        # Now we have an absolute link in terms of localhost.
        # But if it's a bill URL like http://localhost/foo/cache/2018-HB98.html,
        # remap it to the real url of
        # http://www.nmlegis.gov/lcs/legislation.aspx?chamber=H&legtype=B&legno=98&year=18
        if not mapped_url.startswith(self.baseurl):
            return mapped_url

        mapped_url = mapped_url.replace(self.baseurl, '')

        # Now it's just /cache/2018-HB98.html
        if not mapped_url.startswith('/cache/20'):
            return mapped_url
        year = mapped_url[8:10]
        match = re.match('([HS])([A-Z]+)([0-9]+)', mapped_url[11:-5])
        if not match:
            return mapped_url
        chamber, billtype, number = match.groups()
        return self.realbillurlpat % (self.remoteurl, chamber,
                                      billtype, number,
                                      (year_to_2digit(year)))

    def bill_url(self, chamber, billtype, number, year):
        return '%s/cache/20%s-%s%s%s.html' % (self.baseurl,
                                              year_to_2digit(year),
                                              chamber, billtype, number)

    def get_url(self, url):
        return url

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

    def to_local_link(self, url, cururl):
        '''In URLmappers that are local, return a local link
           that won't hit the server.
        '''
        if not url:
            return url

        # XXX This is bogus and will probably not return anything useful,
        # but at least it won't hit the server.
        purl = urlparse(url)
        return './test/%s' % purl.path
