#!/usr/bin/env python

from __future__ import print_function

# Check which bills have been updated since the last check.
# Intended to be run daily.

import billdb
import nmlegisbill
import datetime
import re
import sys, os

import htmlmail

# While testing, use local files:
# nmlegisbill.url_mapper = \
#     nmlegisbill.LocalhostURLmapper('http://localhost/billtracker',
#                                    'https://www.nmlegis.gov',
#         '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')

def show_changes(oldbill, newbill):
    print("Differences in %s" % oldbill['billno'])
    for field in oldbill:
        if oldbill[field] != newbill[field]:
            print(field, oldbill[field], "->", newbill[field])
    print()

def update_all_user_bills():
    '''For every bill any user cares about, update it from the nmlegis
       page if our database hasn't updated it in the last 12 hours.
    '''
    allusers = billdb.all_users()
    allbills = set()
    for user in allusers:
        sep = re.compile('[,\s]+')
        userbills = sep.split(user['bills'])

        for bill in userbills:
            allbills.add(bill)

    allbills = list(allbills)
    allbills.sort()

    newenough = datetime.datetime.now() - datetime.timedelta(hours=1)

    for billno in allbills:
        billdic = billdb.fetch_bill(billno)
        if not billdic['update_date'] or billdic['update_date'] < newenough:
            print("Updating bill", billno)
            billdic = nmlegisbill.parse_bill_page(billno, newenough)

            # Fetch the bill as currently represented in the database,
            # so we can see if anything changed since the last update_date.
            oldbill = billdb.fetch_bill(billno)

            # Compare the old bill and the new one to see if anything changed.
            # update_date will be different, of course, so we'll ignore that.
            oldbill['update_date'] = billdic['update_date']

            # mod_date is None as it comes from parse_bill_page,
            # so set that to the old mod_date; we'll only change it
            # if we actually saw a change.
            billdic['mod_date'] = oldbill['mod_date']

            # XXX TEMPORARY: we're introducing amendlink so oldbill won't have that:
            oldbill['amendlink'] = billdic['amendlink']

            # Now we're ready to compare:
            if billdic != oldbill:
                print("%s changed!" % billno)
                show_changes(oldbill, billdic)
                billdic['mod_date'] = billdic['update_date']

            billdb.update_bill(billdic)
            billdb.commit()
        else:
            print(billno, "is already new enough, not re-fetching")

    return allusers

def Usage():
    print('''Usage: %s smtp_server [smtp_user [smtp_passwd [smtp_port]]]
       %s [--html]

With SMTP information, check bills for all users and send email to each user,
and update the database.
Without SMTP info, print what would be sent, in text (default) or HTML
format, but don't update anything.''' % (os.path.basename(sys.argv[0]),
                                         os.path.basename(sys.argv[0])))
    sys.exit(0)

if __name__ == '__main__':

    html_mode = False
    smtp_server = None
    smtp_user = None
    smtp_passwd = None
    smtp_port = 587
    if len(sys.argv) == 2:
        if sys.argv[1] == '-h' or sys.argv[1] == '--help':
            Usage()
        if sys.argv[1].endswith('html'):
            html_mode = True
        else:
            smtp_server = sys.argv[1]
    elif len(sys.argv) > 1:
        smtp_server = sys.argv[1]
        if len(sys.argv) > 2:
            smtp_user = sys.argv[2]
            if len(sys.argv) > 3:
                smtp_passwd = sys.argv[3]
                if len(sys.argv) > 4:
                    smtp_port = sys.argv[4]

    if not smtp_server:
        print("To send an email, pass server, user, passwd[, port]\n",
              file=sys.stderr)

    billdb.init()

    # Get the list of users and update all user bills from the
    # nmlegis website pages.
    allusers = update_all_user_bills()

    sender = "billtracker@shallowsky.com"

    # Set one "now" to use for updating all the users.
    # But don't call this until we're finished with update_all_user_bills():
    # otherwise it will seem like the bills have been updated more
    # recently than the user.
    now = datetime.datetime.now()

    for user in allusers:
        htmlpart, textpart = billdb.user_bill_summary(user)

        if smtp_server:
            msg = htmlmail.compose_email_msg(user['email'], sender,
                                             html=htmlpart, text=textpart,
                                             subject="New Mexico Bill Tracker")
            htmlmail.send_msg(user['email'], sender, msg,
                              smtp_server, smtp_user, smtp_passwd, smtp_port)
            print("Emailed %s" % user['email'], file=sys.stderr)

            # Now we've updated, so update the user's fetch date.
            billdb.update_user(user['email'], last_check=now)
            billdb.commit()

            continue

        # Not actually sending mail for this user, so just print the parts.
        # If we're not emailing, we also won't update the user's last_check.
        if html_mode:
            print(htmlpart)
            print("<hr>")
        else:
            print(textpart)
            print()


