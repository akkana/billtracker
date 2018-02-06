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

def load_bills_from_users():
    allusers = billdb.all_users()
    allbills = set()
    for user in allusers:
        sep = re.compile('[,\s]+')
        userbills = sep.split(user['bills'])

        for bill in userbills:
            allbills.add(bill)

    allbills = list(allbills)
    allbills.sort()

    for bill in allbills:
        billdic = nmlegisbill.parse_bill_page(bill)
        billdb.update_bill(billdic)

    billdb.commit()

    return allusers

def check_user_bills(user):
    '''user is a dictionary. Check last modified date for each of
       user's bills, see if it's more recent than the user's last check.
       Return summary strings in html and plaintext formats
       (in that order) which can be emailed to the user.
    '''
    # How recently has this user updated?
    last_check = user['last_check']

    # Set up the strings we'll return.
    # Keep bills that have changed separate from bills that haven't.
    newertext = '''Bills that have changed since %s's last check at %s:''' \
               % (user['email'], str(last_check))
    oldertext = '''Bills that haven't changed:'''
    newerhtml = '''<html>
<head>
<style type="text/css">
  div.odd { background: #eef; margin=5px; }
  div.even { background: #efe; margin=5px; }
</style>
</head>
<body>
<h2>%s</h2>''' % newertext
    olderhtml = '<h2>%s</h2>' % oldertext

    # Get the user's list of bills:
    sep = re.compile('[,\s]+')
    userbills = sep.split(user['bills'])

    # For each bill, get the mod_date and see if it's newer:
    even = True
    for billno in userbills:
        even = not even
        billdic = billdb.fetch_bill(billno)
        if billdic['mod_date'] > last_check:
            newertext += '''
%s %s .. updated %s
  Bill page: %s
  Bill text: %s
  History:
%s''' % (billno, billdic['title'], billdic['mod_date'].strftime('%m/%d/%Y'),
         billdic['bill_url'], billdic['contents_url'], billdic['statustext'])
            newerhtml += '''<p>
<div class="%s">
<a href="%s">%s: %s</a> .. updated %s<br />
  <a href="%s">Text of bill</a><br />
  History:
%s
</div>''' % ("even" if even else "odd",
             billdic['bill_url'], billno, billdic['title'],
             billdic['mod_date'].strftime('%m/%d/%Y'),
             billdic['contents_url'], billdic['status'])
        else:
            oldertext += "\n%s %s .. %s" % (billno, billdic['title'],
                                               billdic['mod_date'])
            olderhtml += '<br /><a href="%s">%s %s</a> .. last updated %s' % \
                        (billdic['bill_url'], billno, billdic['title'],
                         billdic['mod_date'])

    return (newerhtml + olderhtml + '</body></html>',
            newertext + "\n===============\n" + oldertext)

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
    allusers = load_bills_from_users()

    sender = "billtracker@shallowsky.com"

    for user in allusers:
        htmlpart, textpart = check_user_bills(user)

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


