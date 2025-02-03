#!/usr/bin/env python3

"""Utilities needed by routes, possibly used other places as well"""


from app import app, db
from app.models import User, Bill, Legislator, Committee, LegSession
from app.bills import nmlegisbill

from flask import session

import re


# filenames are e.g. HB000032.PDF with a random number of zeros.
# Remove all zeros -- but not in the middle of a number, like 103.
# billno_pat = re.compile("([A-Z]*)(0*)([1-9][0-9]*)")

BILLNO_PAT = re.compile("^([SH][JC]{0,1}[BMR])(0*)([0-9]+)$",
                        re.IGNORECASE)


def set_session_by_request_values(values=None):
    """Set the session's yearcode and sessionname according to
       values passed into a requested page.
    """
    if values and "yearcode" in values:
        session["yearcode"] = values["yearcode"]
        session["sessionname"] = \
            LegSession.by_yearcode(session["yearcode"]).sessionname()
    elif "sessionname" not in session:
        leg_session = LegSession.current_leg_session()
        if not leg_session:
            print("Eek! No LegSessions defined. Fetching them...",
                  file=sys.stderr)
            LegSession.update_session_list()
            leg_session = LegSession.current_leg_session()
            if not leg_session:
                print("Double-eek! Couldn't fetch leg sessions",
                      file=sys.stderr)
                return
        session["yearcode"] = leg_session.yearcode
        session["sessionname"] = leg_session.sessionname()


def html_bill_table(bill_list, sortby=None, yearcode=None, inline=False):
    """Return an HTML string showing status for a list of bills
       as HTML table rows.
       Does not inclue the enclosing <table> or <tbody> tags.
       If inline==True, add table row colors as inline CSS
       since email can't use stylesheets.

       XXX Hope to replace this completely and do it in Jinja.
           See bill_email.html for how.
    """
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    sort_key = Bill.get_sort_key(sortby)
    if sort_key:
        bill_list.sort(key=sort_key)

    # Make the table rows alternate color.
    # This is done through CSS on the website,
    # but through inline styles in email.
    if inline:
        rowstyles = [ 'style="background: white;"',
                      'style="background: #cfd; "' ]
        cellstyle = ' style="padding: .5em;"'
    else:
        rowstyles = [ 'class="even"',
                      'class="odd"' ]
        cellstyle = ""

    outstr = ''
    parity = 1
    curday = None
    for bill in bill_list:
        # In a table sorted by last_action, inclue separators
        # between days.
        if sortby == "action_date" and bill.last_action_date:
            newday = bill.last_action_date.date()
            if newday != curday:
                curday = newday
                outstr += "<tr %s><th>Last action: %s\n" \
                    % (rowstyles[0], newday.strftime('%a %m/%d/%Y'))

        parity = 1 - parity
        outstr += '<tr %s><td id="%s"%s>%s\n' % (rowstyles[parity],
                                                 bill.billno,
                                                 cellstyle,
                                                 bill.show_html())

    if not outstr:
        return ""

    return outstr


def make_new_bill(billno, yearcode):
    """Create a new Bill object, not previously in the database,
       by fetching and parsing its page.
       Don't actually add it to the database, just return the Bill object.
    """
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    # Make sure the bill doesn't already exist.
    # This happens sometimes, maybe due to a race condition
    # but I haven't tracked it down yet.
    bills = Bill.query.filter_by(billno=billno, year=yearcode).all()
    if bills:
        print(traceback.format_exc(), file=sys.stderr)
        print("**** Warning: make_new_bill called for bill that already existed",
              file=sys.stderr)
        for b in bills:
            print("    %s (id %d)" % (str(bill), bill.id), file=sys.stderr)
        print("See preceding traceback", file=sys.stderr)

        return bills[0]

    # Populate the new bill by parsing the bill page
    b = nmlegisbill.parse_bill_page(billno, yearcode=yearcode,
                                    cache_locally=True)
    if not b:
        return None

    bill = Bill()
    bill.set_from_parsed_page(b)

    # New way: just make a bill with billno and year,
    # to be filled in from the accdb.
    # But there's a lot of info that won't be picked up in that case,
    # so it's really better to initialize a bill from the bill page.
    # bill = Bill()
    # bill.billno = billno
    # bill.year = yearcode

    # Immediately commit, to reduce (though not entirely eliminate, sigh)
    # race conditions
    db.session.add(bill)
    db.session.commit()

    return bill


# All tags, by yearcode
g_all_tags = {}

def get_all_tags(yearcode):
    if yearcode in g_all_tags:
        return g_all_tags[yearcode]

    all_tags = set()
    for bill in Bill.query.filter_by(year=yearcode).all():
        if bill.tags:
            for tag in bill.tags.split(','):
                all_tags.add(tag)

    g_all_tags[yearcode] = sorted(list(all_tags), key=lambda t: t.lower())
    return g_all_tags[yearcode]

def group_bills_by_tag(bill_list, tag):
    tagged = []
    untagged = []
    for bill in bill_list:
        if not bill.num_tracking():
            continue
        if not bill.tags:
            untagged.append(bill)
            continue

        billtags = bill.tags.split(',')

        # If this page is for all tags, show bills with any tags.
        if not tag:
            if bill.tags:
                tagged.append(bill)
            else:
                untagged.append(bill)

        # If the page is showing a specific tag,
        # group bills according to whether they have that tag.
        elif tag in billtags:
            tagged.append(bill)
        else:
            untagged.append(bill)

    return tagged, untagged
