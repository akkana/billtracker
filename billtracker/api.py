#!/usr/bin/env python3

"""BillTracker API calls, not meant to be visited directly by users"""

from billtracker import billtracker, db
from billtracker.models import User, Bill, Legislator, Committee, LegSession
from billtracker.routeutils import BILLNO_PAT
from billtracker.bills import nmlegisbill
from .routeutils import set_session_by_request_values

from flask import session, request, jsonify

from datetime import date, datetime, timezone, timedelta

import sys, os


@billtracker.route("/api/appinfo/<key>")
def appinfo(key):
    """Display info about the app and the database.
    """
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    infostr = "<br>\nBillTracker at " \
        + str(datetime.now())

    infostr += "<p>\nSQLALCHEMY_DATABASE_URI: " \
        + billtracker.config["SQLALCHEMY_DATABASE_URI"]
    infostr += '<br>\nDatabase: ' + str(db.session.get_bind())

    allusers = User.query.all()
    infostr += "<p>\n%d users registered." % len(allusers)

    # How active are the users?
    now = datetime.now()
    yearcode = LegSession.current_yearcode()
    checked_in_last_day = 0
    never_checked = []
    no_bills = []
    has_current_year_bills = 0
    totbills = 0
    spacer = '&nbsp;&nbsp;&nbsp;&nbsp;'
    for user in allusers:
        if user.last_check:
            print(user, "'s last check:", user.last_check, file=sys.stderr)
            print("now", now, "last_check", user.last_check)
            # Despite herculean efforts, sometimes user.last_check is
            # sometimes coming out tz-aware, which datetime.now() isn't,
            # which causes an exception. Force unaware:
            if now - user.last_check.replace(tzinfo=None) < timedelta(days=1):
                checked_in_last_day += 1
        else:
            never_checked.append(user)

        numbills = len(user.bills)
        if numbills:
            totbills += numbills
            for bill in user.bills:
                if bill.year == yearcode:
                    has_current_year_bills += 1
                    break
        else:
            no_bills.append(user)

    infostr += "<br>\n%swith bills from this session: %d" % (spacer,
                                                      has_current_year_bills)
    infostr += "<br>\n%schecked in past day: %d" % (spacer,
                                                    checked_in_last_day)
    infostr += "<br>\n%snever checked: %d" % (spacer, len(never_checked))
    for user in never_checked:
        infostr += " " + user.username

    infostr += "<br>\n%sno bills in any session: %d" % (spacer, len(no_bills))
    for user in no_bills:
        infostr += " " + user.username

    infostr += "<br>\nAverage bills per user: %d" % (totbills / len(allusers))

    return "OK " + infostr


#
# Background bill updating:
#
# These are queries intended to be called from an update script,
# not from user action, to update bills and other information
# from their respective legislative website pages in the background.
#
# It would be nice to be able to spawn off a separate thread for
# updates, but there doesn't seem to be a way to do that in Flask with
# sqlite3 that's either documented or reliable (it tends to hit
# "database is locked" errors). But WSGI in Apache uses multiple
# threads and that sort of threading does work with Flask, so one of
# those threads will be used for refresh queries.
#


@billtracker.route("/api/refresh_allbills/<key>")
def refresh_allbills(key):
    """Refresh the data needed for the allbills page for the current session
    """
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_allbills: bad key %s" % key, file=sys.stderr)
        return "FAIL Bad key\n"

    yearcode = LegSession.current_yearcode()
    leg_session = LegSession.by_yearcode(yearcode)
    if not leg_session:
        print("refresh_allbills: first need to refresh the session list",
              file=sys.stderr)
        LegSession.update_session_list()
        leg_session = LegSession.by_yearcode(yearcode)
    if not leg_session:
        return "FAIL Couldn't get legislative session list"

    nmlegisbill.update_allbills_if_needed(yearcode, leg_session.id,
                                          force_update=True)
    return "OK Refreshed allbills"


#
# Test with:
# requests.post('%s/api/refresh_one_bill' % baseurl,
#               { "BILLNO": billno, "YEARCODE": yearcode, "KEY": key }).text
#
# XXX PROBLEM: they've started putting bill text in filenames like
# SJR03.html, so now we'll have to look for bill text the same way
# as in refresh_legisdata.
@billtracker.route("/api/refresh_one_bill", methods=['POST'])
def refresh_one_bill():
    """Fetch the page for a bill and update it in the db.
       Send BILLNO, YEARCODE and the app KEY in POST data.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_one_bill: bad key %s" % key, file=sys.stderr)
        return "FAIL Bad key\n"
    billno = request.values.get('BILLNO')

    yearcode = request.values.get('YEARCODE')
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    b = nmlegisbill.parse_bill_page(billno, yearcode, cache_locally=True)
    if not b:
        print("FAIL refresh_one_bill: Couldn't fetch %s bill page" % billno,
              file=sys.stderr)
        return "FAIL Couldn't fetch %s bill page" % billno

    bill = Bill.query.filter_by(billno=billno, year=yearcode).first()
    if not bill:
        bill = Bill()
    bill.set_from_parsed_page(b)

    db.session.add(bill)
    db.session.commit()

    newbill = Bill.query.filter_by(billno=billno, year=yearcode).first()

    return "OK Updated %s" % billno


# Test with:
# requests.post('%s/api/refresh_percent_of_bills' % baseurl,
#               { "PERCENT": percent, "YEAR": year, "KEY": key }).text
# requests.post('%s/api/refresh_percent_of_bills' % baseurl,
#               { "PERCENT": percent, "YEARCODE": yearcode, "KEY": key }).text
@billtracker.route("/api/refresh_percent_of_bills", methods=['GET', 'POST'])
def refresh_percent_of_bills():
    """Refresh a given percentage of the bill list
       for a specified yearcode or year.
       If a year is given, refresh that percentage of bills
       within all yearcodes from that year.
       This is necessary because a special session may be called
       before all the bills from the previous session have been signed.
       If neither yearcode nor year is specified, refresh the current year.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_one_bill: bad key %s" % key, file=sys.stderr)
        return "FAIL Bad key\n"

    percent = request.values.get("PERCENT")
    if percent:
        try:
            percent = int(percent)
        except ValueError:
            return "FAIL: Don't understand '%s' PERCENT" % percent

    yearcode = request.values.get('YEARCODE')
    if yearcode:
        yearcode_list = [ yearcode ]
    else:
        year = request.values.get('YEAR')
        if not year:
            yearcode = LegSession.current_yearcode()
            if len(yearcode) < 2:
                return "FAIL Can't get current yearcode"
            year = yearcode[:2]
        yearcode_list = []
        allsessions = LegSession.query.order_by(LegSession.id).all()
        for ls in allsessions:
            yc = ls.yearcode
            if yc.startswith(year):
                yearcode_list.append(yc)

    # Now yearcode_list is a list of session names (yearcodes)
    retstr = "OK Refreshed %d%% of bills:" % percent
    for yearcode in yearcode_list:
        allbills = Bill.query.filter_by(year=yearcode) \
                             .order_by(Bill.update_date).all()
        if not allbills:
            print("No bills in", yearcode, file=sys.stderr)
            continue

        num2update = len(allbills) * percent // 100
        if not num2update:
            num2update = 1

        bill_list = allbills[:num2update]
        print("Updating %d%% of bills in %s (%s bills): %s"
              % (percent, yearcode, num2update,
                 ', '.join([b.billno for b in bill_list])),
              file=sys.stderr)

        updated_bills = []
        failed_updates = []
        for bill in bill_list:
            b = nmlegisbill.parse_bill_page(bill.billno, yearcode)
            if not b:
                print("Failed to refresh:", bill, file=sys.stderr)
                failed_updates.append(bill.billno)
                continue
            bill.set_from_parsed_page(b)
            updated_bills.append(bill)
            db.session.add(bill)

        retstr += "\n%4s: Updated %s" % (
            yearcode, ' '.join([b.billno for b in updated_bills]))
        if failed_updates:
            retstr += "\n      Failed to update: %s" % (
            ' '.join([str(b) for b in failed_updates]))

    db.session.commit()
    return retstr


# Test:
# SERVERURL/api/refresh_session_list?KEY=KEY
# requests.post('%s/api/refresh_session_list' % baseurl, { "KEY": KEY }).text
@billtracker.route("/api/refresh_session_list", methods=['POST', 'GET'])
def refresh_session_list():
    """Fetch Legislation_List (the same file that's used for allbills)
       and check the menu of sessions to see if there's a new one.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_session_list: bad key %s" % key, file=sys.stderr)
        return "FAIL Bad key\n"

    LegSession.update_session_list()
    return "OK Refreshed list of legislative sessions"


@billtracker.route("/api/bills_by_update_date", methods=['GET', 'POST'])
def bills_by_update_date():
    """Return a list of bills in the current legislative yearcode,
       sorted by how recently they've been updated, oldest first.
       No key required.
    """
    yearcode = request.values.get('yearcode')
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    bill_list = Bill.query.filter_by(year=yearcode) \
                          .order_by(Bill.update_date).all()

    return ','.join([ bill.billno for bill in bill_list ])


# Update LESC, FIR, amendments
# (relatively long-running, see comment above re threads).
#
# Test with:
# posturl = '%s/api/refresh_legisdata' % baseurl
# lescdata = { "TARGET": "LESClink",
#              "URL": "ftp://www.nmlegis.gov/LESCAnalysis",
#              "YEARCODE": "19",    # optional
#              "KEY": '...' }
# firdata = { "TARGET": "FIRlink", "URL": "ftp://www.nmlegis.gov/firs",
#             "YEARCODE": "19",    # optional, default to current
#             "KEY": '...' }
# amenddata = { "TARGET": "amendlink",
#               "URL": "ftp://www.nmlegis.gov/Amendments_In_Context",
#               "YEARCODE": "19",    # optional
#               "KEY": '...' }
# requests.post(posturl, xyzdata).text
@billtracker.route("/api/refresh_legisdata", methods=['POST'])
def refresh_legisdata():
    """Fetch a specific file from the legislative website in a separate thread,
       which will eventually update a specific field in the bills database.
       This is used for refreshing things like FIR, LESC, amendment links.
       POST data required:
         TARGET is the field to be changed (e.g. FIRlink);
         URL is the ftp index for that link, e.g. ftp://www.nmlegis.gov/firs/
         KEY is the app key.
    """
    # XXX the nmlegis parts of this function should move to bills/nmlegisbill
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    yearcode = request.values.get('YEARCODE')
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    target = request.values.get('TARGET')

    url = request.values.get('URL')
    if not url:
        url = "https://www.nmlegis.gov/Sessions/%s/" \
            % nmlegisbill.yearcode_to_longURLcode(yearcode)
        if target == "LESClink":
            url += "LESCAnalysis"
        elif target == "FIRlink":
            url += "firs"
        elif target == "amendlink":
            url += "Amendments_In_Context"
        else:
            errstr = \
                "refresh_legisdata: unknown target %s and no URL specified" \
                % target
            print(errstr, file=sys.stderr)
            return "FAIL " + errstr

    print("refresh_legisdata %s from %s" % (target, url), file=sys.stderr)

    try:
        # XXX Warning: the ftp stuff hasn't been tested recently.
        if url.startswith("ftp:"):
            index = billrequests.ftp_url_index(url)
        else:
            index = billrequests.get_html_dirlist(url)
    except Exception as e:
        print("Couldn't fetch", url, file=sys.stderr)
        print(e, file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return "FAIL Couldn't fetch %s" % url

    # Slow part is done. Now it's okay to access the database.

    changes = []
    not_in_db = []
    badfilenames = []
    # index is a list of dicts with keys name, url, size, Last Modified
    for filedic in index:
        base, ext = os.path.splitext(filedic["name"])

        try:
            # Remove those extra zeros
            match = BILLNO_PAT.match(base)
            billno = match.group(1) + match.group(3)
        except:
            badfilenames.append(base)
            continue

        bill = Bill.query.filter_by(billno=billno, year=yearcode).first()

        if bill:
            setattr(bill, target, filedic["url"])
            db.session.add(bill)
            changes.append(billno)
        else:
            not_in_db.append(billno)

    if not changes:
        print("refresh_legisdata %s: no bills updated" % target)
        return "OK but no bills updated"

    db.session.commit()

    retmsgs = ["Updated %s for %s" % (target, ','.join(changes))]
    if not_in_db:
        retmsgs.append("Has %s but not in db: %s"
                       % (target, ','.join(not_in_db)))
    if badfilenames:
        retmsgs.append("Filenames that don't map to a billno: %s"
                       % ','.join(badfilenames))

    print("refresh_legisdata:", '; '.join(retmsgs))
    return "OK " + "<br>\n".join(retmsgs)


@billtracker.route("/api/refresh_legislators", methods=['GET', 'POST'])
@billtracker.route("/api/refresh_legislators/<key>")
def refresh_legislators(key=None):
    """POST data is only for specifying KEY.
    """
    if not key:
        key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    if Legislator.refresh_legislators_list():
        return "OK Refreshed legislators"

    return "FAIL Couldn't refresh legislator list"


@billtracker.route("/api/all_committees")
def list_committees():
    """List all committee codes in the db, in no particular order.
       No key required.
    """
    all_committees = Committee.query.all()
    if not all_committees:
        print("No committees were set! Should refresh all of them.",
              file=sys.stderr)
        # refresh_all_committees(billtracker.config["SECRET_KEY"])
        # all_committees = Committee.query.all()
        return "FAIL no committees in db"

    return ','.join([ c.code for c in all_committees ])


@billtracker.route("/api/refresh_all_committees/<key>")
def refresh_all_committees(key):
    """Update all committees based on the latest list of upcoming
       committee meetings. Update bills' scheduled_date.
    """
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    print("api/refresh_all_committees", file=sys.stderr)

    set_session_by_request_values()
    yearcode = session["yearcode"]
    thisyear = date.today().year

    # First update the legislators list:
    Legislator.refresh_legislators_list()

    known_committees = Committee.query.all()

    comm_mtgs = nmlegisbill.expand_committees()

    # Are there any new committees in comm_mtgs not yet in the database?
    for commcode in comm_mtgs:
        comm = Committee.query.filter_by(code=commcode).first()
        if not comm:
            newcomm = Committee()
            newcomm.code = commcode

            # Need to add the new committee to the database before refreshing,
            # to avoid sqlite3.IntegrityError: UNIQUE constraint failed
            db.session.add(newcomm)
            db.session.commit()
            # except that even after this,
            # Committee.query.filter_by(code=commcode).first()
            # sometimes returns None. Sigh.

            # Now it should be safe to refresh
            newcomm.refresh()

    hasmeetings = []
    nomeetings = []
    bills_with_committee = {}
    for comm in Committee.query.all():
        if comm.code not in comm_mtgs or not comm_mtgs[comm.code]:
            comm.mtg_time = None
            nomeetings.append(comm.code)
            continue

        if "meetings" not in comm_mtgs[comm.code]:
            nomeetings.append(comm.code)
            continue

        # XXX Currently the Committee database object can only
        # handle one meeting at once, and this code doesn't yet
        # try to handle multiple meetings.

        # Sort this committee's by datetime. Items missing time will have
        # time of 00:00 and so will come before items with a
        # time on the same day.
        # comm_mtgs[comm.code]["meetings"].sort(
        #     key=lambda m: m["datetime"] if "datetime" in m else "zzz")

        # Now update the committee's comm.mtg_time (a string) to show
        # meeting time and details. mtg["timestr"] is a free-form string
        # like "1:30 PM  (or 15 minutes following the floor session)"
        timestrings = []
        updated_comm = False
        today = datetime.now() - timedelta(hours=4)
        for mtg in comm_mtgs[comm.code]["meetings"]:
            # Ignore any meeting without datetime or bills field.
            if "datetime" not in mtg:
                nomeetings.append(comm.code)
                continue
            if "bills" not in mtg:
                nomeetings.append(comm.code)
                continue

            if "timestr" in mtg:
                timestr = mtg["timestr"]
                # May include other details like zoom and schedule links
            elif type(mtg["datetime"]) is datetime and mtg["datetime"].hour:
                timestr = mtg["datetime"].strftime("%H:%M")
            else:
                timestr = ""

            comm.mtg_time = timestr

            for billno in mtg["bills"]:
                if billno in bills_with_committee:
                    if comm.code not in bills_with_committee[billno]:
                        bills_with_committee[billno].append(comm.code)
                else:
                    bills_with_committee[billno] = [comm.code]

                bill = Bill.query.filter_by(billno=billno,
                                            year=yearcode).first()
                if not bill:
                    continue

                bill.location = comm.code
                if not mtg['datetime']:
                    bill.scheduled_date = None
                    print("Warning:", bill,
                          "listed in meeting with no date", mtg,
                          file=sys.stderr)
                    continue

                if not bill.scheduled_date:
                    bill.scheduled_date = mtg['datetime']
                    updated_comm = True

                # Only overwrite an existing scheduled_date
                # if the new one is earlier or if the current
                # datetime is more than a few hours old.
                # Do all comparisons with unaware datetimes
                # because storing local timezone in the database
                # doesn't work reliably. That means the bogus tz
                # postgres automatically adds has to be stripped.
                else:
                    mtg['datetime'].replace(tzinfo=None)
                    sched_time = bill.scheduled_date.replace(tzinfo=None)
                    if sched_time < today or mtg['datetime'] < sched_time:
                        bill.scheduled_date = mtg['datetime']

                    if mtg['datetime'] < sched_time:
                        # XXX Somehow, this message isn't really picking up
                        # mtg['datetime']; it's printing the earlier
                        # meeting time both times.
                        print("CONFLICT:", billno, "scheduled for",
                              bill.scheduled_date, "but also for",
                              mtg['datetime'], file=sys.stderr)

                    updated_comm = True

                db.session.add(bill)

        if updated_comm:
            hasmeetings.append(comm.code)
            db.session.add(comm)
        else:
            nomeetings.append(comm.code)

        db.session.add(comm)

    # Having looped through all the meetings, now clean up any bills
    # that aren't scheduled any longer.

    # Remove any bills that used to be assigned to this committee
    # but no longer are (so they're not in billnos).
    unscheduled = []
    for bill in Bill.query.filter_by(year=yearcode).all():
        if bill.billno not in bills_with_committee:
            bill.scheduled_date = None
            db.session.add(bill)
            unscheduled.append(bill.billno)

    # XXX Sometimes there are joint committee meetings,
    # in which case a bill may be listed for more than
    # one committee. In that case, the bill's location
    # should be set from the bill's HTML page, which
    # means it should be re-parsed here.
    for billno in bills_with_committee:
        if billno in bills_with_committee and \
           len(bills_with_committee[billno]) > 1:
            print("***", billno, "is in multiple committees:",
                  ' '.join(bills_with_committee[billno]), file=sys.stderr)

    db.session.commit()

    billnos = sorted(list(bills_with_committee.keys()))
    unscheduled.sort()
    return "OK\n<br>Committees meeting: " + ",".join(hasmeetings) \
        + "\n<br>No meetings, or no followed bills: " \
        + ",".join(nomeetings) \
        + "\n<br>" \
        + "\n<br>Bills updated: " + " ".join(billnos) \
        + "\n<br>Bills not scheduled: " + " ".join(unscheduled)


def refresh_one_committee(comcode):
    newcom = nmlegisbill.expand_committee(comcode)
    if not newcom:
        print("Couldn't expand committee %s" % comcode, file=sys.stderr)
        return "FAIL Couldn't expand committee %s" % comcode

    com = Committee.query.filter_by(code=comcode).first()
    if not com:
        com = Committee()
        com.code = comcode

    com.update_from_parsed_page(newcom)

    db.session.add(com)
    db.session.commit()

    return "OK Updated committee %s" % comcode


@billtracker.route("/api/refresh_committee/<comcode>/<key>")
def refresh_committee(comcode, key):
    """Long-running API: update a committee from its website.
       POST data includes COMCODE and KEY.
    """
    # key = request.values.get('KEY')
    # if key != billtracker.config["SECRET_KEY"]:
    #     return "FAIL Bad key\n"

    # comcode = request.values.get('COMCODE')
    # if not comcode:
    #     return "FAIL No COMCODE\n"

    return refresh_one_committee(comcode)


@billtracker.route("/api/db_backup", methods=['GET', 'POST'])
def db_backup():
    """Make a backup copy of the database.
       POST data is only for KEY.
    """

    values = request.values.to_dict()

    try:
        key = values['KEY']
        if key != billtracker.config["SECRET_KEY"]:
            return "FAIL Bad key\n"
    except KeyError:
        return "FAIL No key"

    db_uri = billtracker.config['SQLALCHEMY_DATABASE_URI']
    print("db URI:", db_uri, file=sys.stderr)

    now = datetime.now()
    backupdir = os.path.join(billrequests.CACHEDIR, "db")

    db_orig = db_uri[9:]

    if not os.path.exists(backupdir):
        try:
            os.mkdir(backupdir)
        except Exception as e:
            return "FAIL Couldn't create backupdir %s: %s" % (backupdir, str(e))

    if not os.path.exists(backupdir):
        return "FAIL No backupdir %s" % (backupdir)

    if db_uri.startswith('sqlite://'):
        db_new = os.path.join(backupdir,
                              now.strftime('billtracker-%Y-%m-%d_%H:%M.db'))
        shutil.copyfile(db_orig, db_new)

    elif db_uri.startswith('postgresql://'):
        db_new = os.path.join(backupdir,
            now.strftime('billtracker-%Y-%m-%d_%H:%M.psql'))
        # pg_dump dbname > dbname-backup.pg
        with open(db_new, 'w') as fp:
            subprocess.call(["pg_dump", "nmbilltracker"], stdout=fp)
            print("Backed up to", db_new, file=sys.stderr)

    else:
        return "FAIL db URI doesn't start with sqlite:// or postgresql://"

    return "OK Backed up database to '%s'" % (db_new)


def find_dups(yearcode=None):
    """Return a list of all bills that have duplicate entries in the db:
       multiple bills for the same billno and year.
       Return a list of lists of bills.
       Return only the master bill for each billno.
    """

    # A list of all bills that have duplicates, same billno and year.
    dup_bill_lists = []
    bill_ids_seen = set()

    if yearcode:
        bills = Bill.query.filter_by(year=yearcode).all()
    else:
        bills = Bill.query.all()

    for bill in bills:
        # Already seen because it was a dup of something else?
        if bill.id in bill_ids_seen:
            continue

        bill_ids_seen.add(bill.id)

        bills_with_this_no = Bill.query.filter_by(billno=bill.billno,
                                                  year=bill.year) \
                                       .order_by(Bill.id).all()
        if len(bills_with_this_no) == 1:
            continue

        # There are multiple bills with this billno.
        dup_bill_lists.append(bills_with_this_no)

        for dupbill in bills_with_this_no:
            bill_ids_seen.add(dupbill.id)

    return dup_bill_lists


@billtracker.route('/api/showdups/<key>')
@billtracker.route('/api/showdups/<key>/<yearcode>')
def show_dups(key, yearcode=None):
    """Look for duplicate bills in a given yearcode, or all years.
       Return JSON showing dup bills and who's tracking them.
    """
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    ret_json = {}

    dup_bill_lists = find_dups(yearcode)

    if not dup_bill_lists:
        print("No duplicate bills in database, whew", file=sys.stderr)
        return "OK No dups"

    print("duplicate bills:", dup_bill_lists, file=sys.stderr)

    for duplist in dup_bill_lists:
        ret_json[duplist[0].billno] = []
        # The master will be the first, the one with the smallest ID
        min_id = min([b.id for b in duplist])
        masterbill = Bill.query.filter_by(id=min_id).first()

        ret_json[masterbill.billno] = [ {
            'id': masterbill.id,
            'followers': [ u.username for u in masterbill.users_tracking() ]
        } ]

        for b in duplist:
            if b == masterbill:
                continue
            ret_json[b.billno].append({
                'id': b.id,
                'followers': [ u.username for u in b.users_tracking() ]
            })

    return jsonify(ret_json)


# Clean out duplicates.
# This shouldn't be needed, but somehow, duplicates appear.
@billtracker.route('/api/cleandups/<key>')
@billtracker.route('/api/cleandups/<key>/<yearcode>')
def clean_dups(key, yearcode=None):
    if key != billtracker.config["SECRET_KEY"]:
        return "{ 'error': 'FAIL Bad key' }"

    billdups = find_dups(yearcode)
    # billdups is a list of pairs/triples/whatever of bills
    # with the same billno and yearcode

    if not billdups:
        print("No duplicate bills in database, whew", file=sys.stderr)
        return "OK"

    print("billdups:", billdups, file=sys.stderr)
    outstr = "OK<br>\n"

    def trackstr(b):
        return ', '.join([u.username for u in b.users_tracking()])

    deleted = []
    for duplist in billdups:
        # The master will be the first, the one with the smallest ID
        min_id = min([b.id for b in duplist])
        masterbill = Bill.query.filter_by(id=min_id).first()

        outstr += "<br><br>\n\n** %s: id %d, tracked by %s" % (masterbill.billno,
                                                          masterbill.id,
                                                          trackstr(masterbill))
        for b in duplist:
            if b == masterbill:
                continue
            outstr += "<br>\n . . %s (id %d) tracked by %s" % (b.billno, b.id,
                                                            trackstr(b))
            for u in b.users_tracking():
                u.bills.remove(b)
                if masterbill not in u.bills:
                    u.bills.append(masterbill)
                    outstr += "<br>\n . . . . Moved %s to masterbill" % \
                        u.username

            if b.users_tracking():
                print("<br> . . . EEK, failed to remove users from id %d before deleting" % b.id)
            else:
                deleted.append(b)
                outstr += "<br>\n . . Deleting bill with id %d" % b.id
                db.session.delete(b)

        outstr += "<br>\n . Now master bill %d is tracked by: %s" % \
            (masterbill.id, trackstr(masterbill))

    db.session.commit()

    outstr += "<br><br>\nAll bills to delete: %s" % \
        ', '.join(["id %d" % b.id for b in deleted])

    print(outstr, file=sys.stderr)
    return outstr

