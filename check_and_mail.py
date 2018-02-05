#!/usr/bin/env python

# Check which bills have been updated since the last check.
# Intended to be run daily.

import billdb
import nmlegisbill
import datetime
import sys

import htmlmail

# While testing, use local files:
nmlegisbill.url_mapper = \
    nmlegisbill.LocalhostURLmapper('http://localhost/billtracker',
                                   'https://www.nmlegis.gov',
        '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')

def compose_msg(all_bills):
    userbills = billdb.get_user_bills(user['email'])
    if not userbills:
        print("%s isn't tracking any bills" % user['email'])
        return

    text_part = ''
    html_part = ''
    lastdate = user['last_check']
    for bill in userbills:
        print('Bill:', bill)
        b = all_bills[bill]

        timestr = b['mod_date'].strftime('%m/%d/%Y %H:%M')

        text_part += '''%s: %s
    <%s>
Last updated %s
Current location: %s
   <%s>
Text of bill: %s
Status:
%s
''' % \
            (b['billno'], b['title'], b['bill_url'],
             timestr, b['curloc'], b['curloclink'],
             b['contents_url'], b['statustext'])

        html_part += '''<p><a href="%s">%s: %s</a><br />
Last updated %s<br />
Current location: <a href="%s">%s</a><br />
<a href="%s">Text of bill</a><br />
Status:<br />
%s''' % \
            (b['bill_url'], b['billno'], b['title'],
             timestr, b['curloclink'], b['curloc'],
             b['contents_url'], b['status'])

    print(text_part)

    # Now we have plaintext and html parts.
    return htmlmail.compose_email_msg("akkana@shallowsky.com",
                                      "billtracker@shallowsky.com",
                                      html=html_part, text=text_part,
                                      subject="New Mexico Bill Tracker")

if __name__ == '__main__':
    billdb.init()
    bill_list = billdb.all_bills()
    # A list of billdics, like:
    # [{'billno': 'SB83', 'mod_date': '2018-01-18'},
    #  {'billno': 'SJM6', 'mod_date': '2018-01-10'}]
    # Fill them in from the website.

    all_bills = {}
    for i, bill in enumerate(bill_list):
        all_bills[bill['billno']] = nmlegisbill.parse_bill_page(bill['billno'])

    print("all_bills:\n", all_bills)
    print('')

    if len(sys.argv) < 4:
        print("To send an email, pass server, user, passwd[, port]")
        sys.exit(0)

    smtp_server = sys.argv[1]
    smtp_user = sys.argv[2]
    smtp_passwd = sys.argv[3]
    if len(sys.argv) > 4:
        smtp_port = sys.argv[4]
    else:
        smtp_port = 587

    all_users = billdb.all_users()
    for user in all_users:
        msg = compose_msg(all_bills)
        if not msg:
            print("Eek, msg didn't get set")
            print("exiting, not sending")
            sys.exit(1)

        htmlmail.send_msg("akkana@shallowsky.com",
                          "billtracker@shallowsky.com",
                          msg,
                          smtp_server, smtp_user, smtp_passwd, smtp_port)
    print("Supposedly sent the mail")
