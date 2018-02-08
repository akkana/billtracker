#!/usr/bin/env python

from __future__ import print_function

# Check which bills have been updated since the last check.
# Intended to be run daily.

import billdb
import nmlegisbill
import datetime
import re
import sys

import htmlmail

# While testing, use local files:
# nmlegisbill.url_mapper = \
#     nmlegisbill.LocalhostURLmapper('http://localhost/billtracker',
#                                    'https://www.nmlegis.gov',
#         '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')

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

    newenough = datetime.datetime.now() - datetime.timedelta(hours=12)

    for billno in allbills:
        billdic = billdb.fetch_bill(billno)
        if not billdic['mod_date'] or billdic['mod_date'] < newenough:
            print("Updating bill", billno)
            billdic = nmlegisbill.parse_bill_page(billno, newenough)
            billdb.update_bill(billdic)
            billdb.commit()
        else:
            print(billno, "is already new enough, not re-fetching")

    return allusers

if __name__ == '__main__':

    html_mode = False
    smtp_server = None
    smtp_user = None
    smtp_passwd = None
    smtp_port = 587
    if len(sys.argv) == 2 and sys.argv[1].endswith('html'):
        html_mode = True
    elif len(sys.argv) > 1:
        smtp_server = sys.argv[1]
        if len(sys.argv) > 2:
            smtp_user = sys.argv[2]
            if len(sys.argv) > 3:
                smtp_passwd = sys.argv[3]
                if len(sys.argv) > 4:
                    smtp_port = sys.argv[4]

    if not smtp_server:
        print("To send an email, pass server, user, passwd[, port]",
              file=sys.stderr)

    now = datetime.datetime.now()

    billdb.init()

    # Get the list of users and update all user bills from the
    # nmlegis website pages.
    allusers = update_all_user_bills()

    sender = "billtracker@shallowsky.com"

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
        if html_mode:
            print(htmlpart)
            print("<hr>")
        else:
            print(textpart)
            print()


