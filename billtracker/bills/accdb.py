#!/usr/bin/env python3

"""Some convenience wrappers to handle Microsoft Access .accdb files
   on non-Windows platforms.
   Uses the command-line mdbtools utilities.
"""

# Why not pyodbc? Couldn't get it to work.
# pyodbc apparently used to include its own msdb driver,
# and later switched to working with unixodbc,
# but as of Jan 2024 neither of those is true,
# either in the Debian package
# or from the pypi package after installing unixodbc-dev.

import subprocess
from datetime import datetime
from dateutil.parser import parse as parsedate
import requests
import time
import re
import zipfile
import json
from io import BytesIO
import os
import sys

from billtracker import db
from billtracker.models import Bill

# The main accdb file is downloaded with the regular requests module,
# but billrequests is used for things like the cachedir
from billtracker.bills import billrequests

# How long is too long to wait for a lock file while downloading the accdb?
# Let's say 1 minute (this is in seconds).
LOCKED_TOO_LONG = 60


def update_bills(bill_list):
    """Update a list of bills in the flask database based on any changes
       to the accdb.
       bill_list is a list of Bill objects from models.py.
    """
    print("****** Will try to update:", bill_list)
    accdbfile = fetch_accdb_if_needed(billrequests.CACHEDIR)

    # XXX Might it be faster to formulate a query that uses mdb-sql?
    # It would certainly use less memory.
    billtable = read_bill_table(accdbfile)

    changed = False
    firstbill = None
    now = datetime.now()
    for bill in bill_list:
        billchanged = False
        accbill = billtable[bill.billno]
        if not accbill:
            print("Eek, tried to update bill %s not in the accdb" % bill.billno,
                  file=sys.stderr)
            continue

        # Update all the fields that have changed
        def update_if(accdbfield, btfield):
            nonlocal billchanged
            if accbill[accdbfield] != bill.__getattribute__(btfield) \
               and accbill[accdbfield]:
                bill.__setattr__(btfield, accbill[accdbfield])
                billchanged = True

        update_if('Title', 'title')
        update_if('Session', 'year')
        # XXX do something about bill.last_action_date
        update_if('Chamber', 'chamber')
        update_if('LegType', 'billtype')
        update_if('LegNo', 'number')

        # use decodenmlegis to turn accbill['ActionText'] and
        # accbill['CommitteeVotes'] into bill.statustext
        # and also update statusHTML
        accbill['ActionText'] = '\n' + accbill['ActionText'].strip()
        update_if('ActionText', 'statustext')

        update_if('LocationCode', 'location')

        # Get up to 4 sponsors, which are in 'SponsorCode',
        # 'SponsorCode1', 'SponsorCode2' etc
        sponsors = accbill['SponsorCode']
        for i in range(1, 4):
            accfield = 'SponsorCode%d' % i
            if accfield in accbill:
                sponsors = ','.join([ sponsors, accbill[accfield] ])
        if sponsors != bill.sponsor:
            bill.sponsor = sponsors
            billchanged = True

        # Sadly, the accdb doesn't have contentslink, FIRlink etc.

        # ScheduledDate is something like '01/26/24 00:00:00'
        # so we have to ignore the time.
        # HearingTime is a free-form string, could be '8:30 AM' or
        # '1:30 PM or 1/2 hour after floor session'.
        # It's more reliable to get meeting time from the committees,
        # so only update ScheduleDate here if there was none previously,
        # and ignore HearingTime if it's nontrivial.
        timematch = None
        if 'HearingTime' in accbill:
            hearingtime = accbill['HearingTime'].strip()
            if hearingtime:
                timematch = re.match(r'(\d{1,2}):(\d\d) *([ap])\.*m',
                                     hearingtime)
        if 'ScheduledDate' in accbill and accbill['ScheduledDate'] \
           and not bill.scheduled_date:
            sched_date = datetime.strptime(accbill['ScheduledDate'],
                                           '%m/%d/%y %H:%M:%S')
            if timematch:
                try:
                    hour = int(timematch.group(1))
                    minute = int(timematch.group(2))
                    if timematch.group(3).lower() == 'p':
                        hour += 12
                    sched_date = sched_date.replace(hour=hour, minute=minute)
                except Exception as e:
                    print("Problem parsing time:", e, file=sys.stderr)
                    print("Match was", timematch.group(0), file=sys.stderr)
            bill.scheduled_date = sched_date
            billchanged = True

        if billchanged:
            bill.update_date = now
            db.session.add(bill)
            changed = True
            print(bill, "changed", file=sys.stderr)
        else: print("Bill", bill, "didn't change", file=sys.stderr)

    if changed:
        db.session.commit()
        print("Committed changes", file=sys.stderr)
    else:
        print("Nothing changed", file=sys.stderr)


def fetch_accdb_if_needed(localdir):
    """Fetch the LegInfoYY.zip file from nmlegis.gov if web headers
       say it's newer than our cached file.
       Unzip it and cache the .accdb file.
       Return the full path to the unzipped file.
       This db is typically updated daily in the early afternoon (3:30-4)
       but sometimes gets smaller updates later in the evening.
    """
    now = datetime.now()
    yearcode = now.strftime("%y")
    remote = 'https://nmlegis.gov/Sessions/%s%%20Regular/other/LegInfo%s.zip' \
        % (yearcode, yearcode)
    accdbname = None
    # localfile = now.strftime("LegInfo-%y-%m-%dT%H.accdb")
    localfile = "LegInfo.accdb"

    return fetch_remote_if_needed(remote, os.path.join(localdir, localfile))


def fetch_remote_if_needed(url, localfile):
    """
    Fetch from url to a file (full path) named localfile
    only if the last modified date of the url is newer than localfile.
    Return localfile.
    """
    urltime = None
    if os.path.exists(localfile):
        print("localfile", localfile, "exists")
        if billrequests.LOCAL_MODE:
            print("LOCAL_MODE and file exists", file=sys.stderr)
            return localfile

        head = billrequests.head(url)
        if 'Last-Modified' in head.headers:
            urltime = parsedate(head.headers['Last-Modified']).astimezone()
            print("URL last mod date parsed to", urltime)
            filetime = datetime.fromtimestamp(os.stat(localfile).st_mtime).astimezone()
            if filetime >= urltime:
                print(localfile, "is already new enough, not fetching",
                      file=sys.stderr)
                return localfile

        else:
            print("No last-modified in headers")
            print(head.headers)
    else:
        print("localfile", localfile, "doesn't exist", file=sys.stderr)

    # At this point fetching a new file is needed.
    # But that's incompatible with LOCAL_MODE.
    if billrequests.LOCAL_MODE:
        raise FileNotFoundError(localfile)

    # Open a lockfile.
    lockfile = localfile + ".lck"
    try:
        os.open(lockfile, os.O_CREAT | os.O_EXCL)
        print("Opened the lockfile", lockfile, file=sys.stderr)
    except FileExistsError:
        # There's already a lock file. If it hasn't been there long,
        # and there's a local file, just use the local file.
        filestat = os.stat(lockfile)
        if os.path.exists(localfile) and \
           time.time() - filestat.st_mtime < LOCKED_TOO_LONG:
            return localfile

        # If no localfile, but the lock hasn't been there long,
        # try waiting a bit for the lock to clear:
        while os.path.exists(lockfile) and not os.path.exists(localfile) and \
              time.time() - filestat.st_mtime < LOCKED_TOO_LONG:
            time.sleep(1)
            try:
                filestat = os.stat(lockfile)
            except FileNotFoundError:
                # lockfile is gone!
                if os.path.exists(localfile):
                    return localfile
                break

    print("Fetching", url, "last mod date", urltime, file=sys.stderr)
    r = requests.get(url)
    with zipfile.ZipFile(BytesIO(r.content)) as zip:
        names = zip.namelist()
        if len(names) > 1:
            print("Too many names in zip archive:", ' '.join(names))
        for name in names:
            if name.endswith('.accdb'):
                accdbname = name
                base, ext = os.path.splitext(accdbname)
                break
        if not accdbname:
            os.unlink(lockfile)
            raise RuntimeError("No zipfile in %s" % url)

        # Rename accdbname to the new file path
        newfile = localfile + ".new"
        zip.getinfo(accdbname).filename = newfile
        # then extract it
        zip.extract(accdbname)
        print("Should have extracted", newfile)

        # Back up the old file, move the new into place
        # and then remove the lockfile
        try:
            if filetime:
                base, ext = os.path.splitext(localfile)
                backupfile = "%s%s%s" % (base,
                                         filetime.strftime("%y-%m-%dT%H"),
                                         ext)
            else:
                backupfile = localfile + ".bak"
            print("Backing up", localfile, "to", backupfile, file=sys.stderr)
            os.rename(localfile, backupfile)
        except Exception as e:
            print("Couldn't back up", localfile, e, file=sys.stderr)

        print("Downloaded new", localfile, file=sys.stderr)
        os.rename(newfile, localfile)
        os.unlink(lockfile)

    return localfile


def list_tables(dbfilename):
    """List all table names in the db"""
    return [ tbl.decode() for tbl in
             subprocess.check_output([ "mdb-tables", "-1",
                                       dbfilename ]).split(b'\n')
             if tbl ]


def read_bill_table(dbfilename):
    """Read the table named 'Legislation', and return a dictionary
       of dictionaries indexed by billno:
       { billno: accdb_dictionary }
    """
    billtable = {}
    for line in read_table_lines(dbfilename, 'Legislation'):
        bill = json.loads(line)
        # Only LegNo currently has spurious spaces, but strip them all
        # just in case
        billno = bill['Chamber'].strip() \
            + bill['LegType'].strip() \
            + bill['LegNo'].strip()
        billtable[billno] = bill

    return billtable


def read_table_lines(dbfilename, tablename):
    """An iterator that reads lines from an accdb table.
       mdb-json doesn't actually print json; it prints a list of lines
       each of which is a json dictionary.
    """
    try:
        for line in subprocess.check_output([
                "mdb-json",
                dbfilename, tablename ]).splitlines():
            yield line
    except FileNotFoundError as e:
        raise RuntimeError("Can't run mdb-json") from e


if __name__ == '__main__':
    accdbfile = fetch_accdb_if_needed('.')
    if not os.path.exists(accdbfile):
        print("Fetching a new", LOCALFILE)
        fetch_remote()

    # tables = list_tables(accdbfile)
    # for tbl in tables:
    #     print(tbl)

    billtable = read_bill_table(accdbfile)

    from pprint import pprint
    print(billtable.keys())
    print()

    # pprint(billtable)

    # firstkey = next(iter(billtable))
    # print(firstkey, ":")
    # pprint(billtable[firstkey])



