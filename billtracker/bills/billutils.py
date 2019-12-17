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


def current_leg_year():
    '''Return the current LEGISLATIVE year as an integer (2019, not 19).
       Starting in November, figure nobody's paying attention to the
       previous session and is looking toward the session that starts
       in January.
    '''
    now = datetime.datetime.now()
    if now.month >= 11:
        return now.year + 1
    return now.year


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

    # Use this year if not defined or in an unknown format.
    return '%02d' % (current_leg_year() - 2000)


def billno_to_parts(billno, year=None):
    '''Split a bill number into its parts: chamber, billtype, number, year.
       Return chamber, billtype, number, year as strings
       suitable for an nmlegis URL.
    '''
    year = year_to_2digit(year)

    # billno is chamber, bill type, digits, e.g. HJM4. Parse that:
    match = re.match('([HS])([A-Z]+) *([0-9]+)', billno)
    if not match:
        raise RuntimeError("I don't understand bill name '%s'" % billno)
    chamber, billtype, number = match.groups()
    return chamber, billtype, number, year

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


def ftp_get(server, dir, filename, outfile):
    '''Fetch a file via ftp.
       Write the content to a file.
    '''
    ftp = FTP(server)
    ftp.login()
    ftp.cwd(dir)

    ftp.retrbinary('%s' % filename, open(outfile, 'wb').write)

    ftp.quit()
    print("Cached in", outfile)


def ftp_index(server, ftpdir):
    '''Read an ftp index page; return the contents as a list of dics,
       [ { 'name': 'SB0048SFL1.pdf, 'size': '136 KB',
           'Last Modified': '1/24/19 	1:19:00 PM MST
         }
       ]
       Note that times are datetimes but no timezone is set.
       Frustratingly, if you view the ftp: URL in a web server it shows
       timezones, but actually retrieving the listing via ftp drops them.
    '''
    # print("Fetching index of %s from %s" % (ftpdir, server))
    ftp = FTP(server)
    ftp.login()
    ftp.cwd(ftpdir)
    ls = []
    # MLST and MLSD are supposedly the right way to do this, but
    # ftp.nmlegis.gov doesn't support it. Uncomment and finish
    # implementing this if your server does offer MLSD.
    # ftp.retrlines('MLSD', ls.append) for entry in ls: print(entry)
    listlines = []
    listout = ftp.retrlines('LIST', listlines.append)

    # Lines for directories:
    # 12-19-18  10:03AM       <DIR>          Legislator Information
    # Lines for files:
    # 01-24-19  04:06PM                93184 Legislators.XLS
    # 01-28-19  12:58PM               288257 HB0005.PDF

    listing = []
    for line in listlines:
        if '<DIR>' in line:
            match = re.match('(\d+-\d+-\d+ +\d+:\d+[AP]M) +<DIR> +(.+)', line)
            if match:
                listing.append([match.group(2),
                                dateutil.parser.parse(match.group(1)),
                                None])
        else:
            match = re.match('(\d+-\d+-\d+ +\d+:\d+[AP]M) +(\d+) +(.+)', line)
            if match:
                listing.append([match.group(3),
                                dateutil.parser.parse(match.group(1)),
                                int(match.group(2))])
    return listing


def ftp_url_index(url):
    '''Read an ftp index page; return the contents as a list of dics.
    '''
    purl = urlparse(url)
    if not purl.scheme:
        netloc = 'www.nmlegis.gov'
    elif purl.scheme == 'ftp':
        netloc = purl.netloc
    else:
        raise RuntimeError("ftp_url_index: bad URL %s" % url)

    return ftp_index(netloc, purl.path)


