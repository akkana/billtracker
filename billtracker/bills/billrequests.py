#!/usr/bin/env python3

"""
A derivative of the requests module, which handles caching
and allows a cache-only mode for testing
(because Python makes it so difficult to mock requests).
Overrides get, post, and head
all of which also take an additional, optional, cachetime (secs).

Also adds
    ftp_get(server, dir, filename, outfile),
    ftp_index(server, ftpdir)
    ftp_url_index(url)
"""


# Derive everything from requests except the calls overridden in this file:
from requests import *
import requests

import re
from bs4 import BeautifulSoup
import os, sys
import time
import dateutil.parser
import traceback

from urllib.parse import urlparse
from ftplib import FTP


#
# Some globals
#

# Default place for the cache
CACHEDIR = 'cache'

# How old a file can be, in seconds, before being replaced
CACHESECS = 2*60*60

# Local mode, don't ever fetch from the network.
# Used for unit testing, because none of the Python packages for mocking
# network requests (mock, requests_mock, httpretty) actually work. Sigh.
LOCAL_MODE = False

# Verbose debugging
DEBUG = False


# requests.Response doesn't allow setting the text member,
# so here's a fake class that does.
class FakeResponse:
    def __init__(self):
        self.status_code = 404
        self.text = None


#
# Override the three important requests module functions
# to consult the cache.
#

def get(url, params=None, **kwargs):
    """Wrapper for requests.get that can fetch from cache instead.
       Optional keyword arguments:
         cachefile: specifies the location of the cache file,
                    otherwise it will be calculated.
         cachesecs: how old a file can be before being replaced,
                    default: CACHESECS
    """
    if DEBUG:
        if LOCAL_MODE:
            print("=== get LOCAL MODE:", url)
        else:
            print("=== get :", url)

    if 'cachefile' in kwargs and kwargs["cachefile"]:
        cachefile = kwargs['cachefile']
    else:
        cachefile = url_to_cache_filename(url)

    if 'cachesecs' in kwargs:
        cachesecs = kwargs['cachesecs']
    else:
        cachesecs = CACHESECS

    # The response that will be returned
    response = FakeResponse()

    if LOCAL_MODE:
        if os.path.exists(cachefile):
            if DEBUG:
                print("LOCAL_MODE: Fetching from cachefile:", cachefile)
            with open(cachefile) as fp:
                response.text = fp.read()
                response.status_code = 200
                return response
            print("Eek, cachefile existed but didn't return?")
        # Cache file doesn't exist, but it's local mode so
        # can't use the net.
        if DEBUG:
            print("*** billrequests.get(): LOCAL_MODE, but "
                  "cachefile %s doesn't exist" % cachefile)
            print("  for URL", url)
        response.status_code = 404
        response.text = None
        return response

    if DEBUG:
        print("**** billrequests.get: NOT LOCAL MODE")

    if os.path.exists(cachefile):
        filestat = os.stat(cachefile)
        if (time.time() - filestat.st_mtime) < cachesecs or cachesecs < 0:
            if DEBUG:
                print("Already cached:", url, '->', cachefile, file=sys.stderr)
            with open(cachefile) as fp:
                response.text = fp.read()
                response.status_code = 200
                return response

    # The cachefile doesn't exist or was too old. Fetch from the net
    # and write to the cachefile.
    # First remove cachefile or cachesecs args that requests isn't expecting:
    if "cachefile" in kwargs:
        del kwargs["cachefile"]
    if "cachesecs" in kwargs:
        del kwargs["cachesecs"]
    print("NETWORK get", url, file=sys.stderr)
    try:
        response = requests.get(url, params, **kwargs)
        if response.status_code == 200:
            with open(cachefile, "w") as cachefp:
                cachefp.write(response.text)
        else:
            print("*** NETWORK ERROR fetching %s: status code was %d"
                  % (url, response.status_code), file=sys.stderr)
    except Exception as e:
        print("*** NETWORK ERROR fetching %s: %s" % (url, str(e)),
              file=sys.stderr)

    return response


def head(url, **kwargs):
    """Wrapper for requests.head that can fetch from cache instead.
       Optional cachefile argument specifies the location of the
       cache file, otherwise it will be calculated.
    """
    if DEBUG:
        if LOCAL_MODE:
            print("=== head LOCAL MODE:", url)
        else:
            print("=== head :", url)

    if 'cachefile' in kwargs and kwargs["cachefile"]:
        cachefile = kwargs['cachefile']
    else:
        cachefile = url_to_cache_filename(url)

    if 'cachesecs' in kwargs:
        cachesecs = kwargs['cachesecs']
    else:
        cachesecs = CACHESECS

    # The response that will be returned
    response = FakeResponse()

    if LOCAL_MODE:
        if DEBUG:
            print("head LOCAL MODE:", url, "->", cachefile)
        if os.path.exists(cachefile):
            response.status_code = 200
        else:
            response.status_code = 404
        return response

    if DEBUG:
        print("**** billrequests.head: NOT LOCAL MODE")

    if os.path.exists(cachefile):
        filestat = os.stat(cachefile)
        if (time.time() - filestat.st_mtime) < cachesecs or cachesecs < 0:
            response.status_code = 200
            return response

    return requests.head(url, **kwargs)


#
# Some other helpful functions for fetching bill-related files.
#


# Bill URLs will match this pattern.
bill_url_pat = re.compile(
    r'https://www.nmlegis.gov/Legislation/Legislation\?'
    r'chamber=([HS])&'
    r'legtype=([JBR]+)&'
    r'legno=([0-9]+)&'
    r'year=([0-9]{2}s?[0-9]*)')


def url_to_cache_filename(url, billdic=None):
    """Calculate the cache filename for the given url.
       If billdic is provided, it will be used for keys 'billno' and 'year'
       otherwise all such information will be parsed from the URL.
    """
    # Is it a bill URL? That's true if billdic is set,
    # or if the bill fits this pattern:
    if billdic:
        return os.path.join(CACHEDIR,
                            '20%s-%s.html' % (billdic['year'],
                                              billdic['billno']))

    bill_url_matcher = bill_url_pat.match(url)
    if bill_url_matcher:
        chamber, billtype, number, yearcode = bill_url_matcher.groups()
        return os.path.join(CACHEDIR,
                            '20%s-%s%s%s.html' % (yearcode, chamber,
                                                  billtype, number))

    # It wasn't a bill URL. Fall back to making a filename
    # that's similar to the one in the URL.
    return os.path.join(CACHEDIR,
                        url.replace('https://www.nmlegis.gov/', '') \
                        .replace('/Legislation', '') \
                        .replace('/', '_') \
                        .replace('?', '_') \
                        .replace('&', '_'))


def soup_from_cache_or_net(url, billdic=None, cachesecs=CACHESECS):
    """url is a full URL including https://www.nmlegis.gov/ .
       If there is a recent cached version, use it,
       otherwise fetch the file and cache it.
       If the cache file is older than cachesecs, replace it.
       If billdic is provided, it will be used for keys 'billno' and 'year'
       to make a cleaner cache file name, like '2020-HB31.html'.
       Either way, return a BS soup of the contents.
    """
    if DEBUG:
        print("=== soup_from_cache_or_net:", url, "billdic", billdic)

    cachefile = url_to_cache_filename(url, billdic)

    response = get(url, cachefile=cachefile, cachesecs=cachesecs)

    if response.status_code != 200:
        print("No soup! Response was", response.status_code, file=sys.stderr)
        print("  on cache %s,\n  URL %s" % (cachefile, url), file=sys.stderr)
        return None

    soup = BeautifulSoup(response.text, "lxml")
    if not soup:
        print("No soup! On cache %s,\n  URL %s" % (cachefile, url),
              file=sys.stderr)

    return soup


# Seriously? requests can't handle ftp?
def ftp_get(server, dir, filename, outfile):
    """Fetch a file via ftp.
       Write the content to a file.
    """
    ftp = FTP(server)
    ftp.login()
    ftp.cwd(dir)

    ftp.retrbinary('%s' % filename, open(outfile, 'wb').write)

    ftp.quit()


def get_http_dirlist(url):
    """Read an ftp dir listing page; return the contents as a list of dics,
       [ { 'name': 'SB0048SFL1.pdf, 'size': '136 KB',
           "url": "https://www.nmlegis.gov/Sessions/20%20Regular/firs/HB0004.PDF",
           'Last Modified': '1/24/19 	1:19:00 PM MST
         }
       ]
       Note that times are datetimes but no timezone is set.
       Frustratingly, if you view the ftp: URL in a web server it shows
       timezones, but actually retrieving the listing via ftp drops them.
    """
    try:
        listing = get(url).text
    except:
        print("No dir list at", url, file=sys.stderr)
        return None

    if not listing:
        return None

    ls = []

    # The listing is inside a <pre>, with lines separated by <br>,
    # and each line is formatted like this:
    #  1/25/2020  7:32 PM       133392 <A HREF="/Sessions/20%20Regular/firs/HB0019.PDF">HB0019.PDF</A><br>
    listing = re.sub(".*<pre>", "", listing, flags=re.IGNORECASE|re.DOTALL)
    listing = re.sub("</pre>.*", "", listing, flags=re.IGNORECASE|re.DOTALL)
    lines = listing.split("<br>")
    hrefpat = re.compile('HREF="([^"]*)">([^<]+)<', flags=re.IGNORECASE)
    for line in lines:
        words = line.split()
        if len(words) != 6:
            continue
        try:
            dic = {}
            dic["size"] = int(words[3])
            month, day, year = [int(n) for n in words[0].split("/")]
            hour, minute = [int(n) for n in words[1].split(":")]
            if words[2] == "PM":
                hour += 12
            dic["Last Modified"] = "%s\t%s %s MST" % tuple(words[0:3])
            # words[5] looks like:
            # 'HREF="/Sessions/20%20Regular/firs/HB0001.PDF">HB0001.PDF</A>'
            match = hrefpat.match(words[5])
            dic["url"] = "https://www.nmlegis.gov/" + match.group(1)
            dic["name"] = match.group(2)

            ls.append(dic)
        except RuntimeError as e:
            continue

    return ls


def ftp_index(server, ftpdir):
    """Read an ftp index page; return the contents as a list of dics,
       [ { 'name': 'SB0048SFL1.pdf, 'size': '136 KB',
           'Last Modified': '1/24/19 	1:19:00 PM MST
         }
       ]
       Note that times are datetimes but no timezone is set.
       Frustratingly, if you view the ftp: URL in a web server it shows
       timezones, but actually retrieving the listing via ftp drops them.
    """
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
    baseurl = "ftp://%s/%s" % (server, ftpdir)
    for line in listlines:
        if '<DIR>' in line:
            match = re.match('(\d+-\d+-\d+ +\d+:\d+[AP]M) +<DIR> +(.+)', line)
            if match:
                listing.append({ "name": match.group(2),
                                 "url": "%s/%s" % (baseurl, match.group(2)),
                                 "Last Modified": dateutil.parser.parse(match.group(1)),
                                 "size": int(match.group(2)) })
        else:
            match = re.match('(\d+-\d+-\d+ +\d+:\d+[AP]M) +(\d+) +(.+)', line)
            if match:
                listing.append({ "name": match.group(3),
                                 "url": "%s/%s" % (baseurl, match.group(3)),
                                 "Last Modified": dateutil.parser.parse(match.group(1)),
                                 "size": int(match.group(2)) })
    return listing


def ftp_url_index(url):
    """Read an ftp index page; return the contents as a list of dics.
    """
    purl = urlparse(url)
    if not purl.scheme:
        netloc = 'www.nmlegis.gov'
    elif purl.scheme == 'ftp':
        netloc = purl.netloc
    else:
        raise RuntimeError("ftp_url_index: bad URL %s" % url)

    return ftp_index(netloc, purl.path)


if __name__ == '__main__':
    pass

