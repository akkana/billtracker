#!/usr/bin/env python3

import cgi

# CGI tracebacks:
import cgitb
cgitb.enable()

import billdb
import nmlegisbill

# While testing, use local files:
nmlegisbill.url_mapper = \
    nmlegisbill.LocalhostURLmapper('http://localhost/billtracker',
                                   'https://www.nmlegis.gov',
        '%s/Legislation/Legislation?chamber=%s&legtype=%s&legno=%s&year=%s')

def header(title):
    print('''Content-type: text/html

<html>
<head>
<title>%s</title>
<style type="text/css">
  table { border-collapse: collapse; }
  table.bill th, table.bill td { border: 2px solid #bbc; }
  dd { font-weight: bold; }
  tr.header th { background: lightblue; }
</style>
</head>

<body>
<h1>%s</h1>
''' % (title, title))

def footer():
    print("</body></html>")

def show_bill_list(bills):
    print('<table class="bill">')
    for bill in bills:
        print('<tr class="header"><th colspan=2>', bill)
        billdic = nmlegisbill.parse_bill_page(bill, 2018)
        if not billdic:
            print("<dt>Error: couldn't find bill", bill)
            continue

        # for key in billdic:
        #     val = billdic[key]
        #     if key.endswith("url") or key.endswith("link"):
        #         print("<dd>%s: <a href='%s'>%s</a>" % (key, val, val))
        #     else:
        #         print("<dd>%s: %s" % (key, val))

        print('<tr><td>Title:<td><a href="%s">%s</a> (<a href="%s">full text</a>)' \
              % (billdic['bill_url'], billdic['title'],
                 billdic['contents_url']))
        print('<tr><td>Sponsor:<td><a href="%s">%s</a>' % (billdic['sponsorlink'],
                                                    billdic['sponsor']))
        print('<tr><td>Current Location:<td><a href="%s">%s</a>' \
              % (billdic['curloclink'], billdic['curloc']))
        print("<tr><td>Most recent action:<td>", billdic['status'])
    print("</table>")

def bills_page():
    form = cgi.FieldStorage()

    header('New Mexico Bill Tracker')

    if "bills" in form:
        bills = form["bills"].value.split(',')
        print("<p>\nBills:", form["bills"].value)
        print("<p>")
        show_bill_list(bills)

    if "user" in form:
        print("<p>\nBills <b>%s</b> is tracking:\n<p>" % form["user"].value)

        billdb.init()

        bills = billdb.get_user_bills(form["user"].value)
        show_bill_list(bills)

    if not form.keys():
        print("Username?")

    footer()

def user_page():
    billdb.init()

    form = cgi.FieldStorage()

    # Whether for new users or old, we want to know if the user
    # has already specified any bills:
    if "bills" in form:
        billstring = form["bills"].value
        # XXX Security: capitalize andrestrict this to
        # XXX letters, digits, comma and space.
    else:
        billstring = ''

    # Are we specifying a user?
    if "user" in form:
        username = form["user"].value

        # Have we just confirmed the form, so we should save changes?
        if "Confirm" in form:
            header("Changes confirmed for user %s" % username)
            # print("confirm CGI:", form)

            # XXX Make database changes here
            print("<p>Should be making database changes here")
            footer()
            return

        header("New Mexico Bill Tracker: Edit User %s" % username)
        # print("user CGI:", form)

        if billdb.exists_in_db(username, "users"):
            print('''<h2>%s's bills:</h2>
<form method="post" action="user.cgi">
<input type="hidden" name="user" value="%s">
''' % (username, username))
            bills = billdb.get_user_bills(username)
            print('<table>')
            for bill in bills:
                print('<tr><td><input name=%s type="checkbox" checked>' % bill)
                billdic = nmlegisbill.parse_bill_page(bill, 2018)
                if not billdic:
                    print('<td>Couldn\'t find bill %s''' % bill)
                    continue
                print('<td>%s %s' % (billdic['title'], bill))
            print('''</table>
<p>
Additional bills to track (comma or space separated):
<input type="text" name="bills" size=45 value="%s">
<p>
<input type="submit" name="Confirm"
       value="Confirm changes for %s">''' % (billstring, username))

        else:
            # username is a new user, not yet in the database
            print('''<p>%s is a new user!
<p>
<form method="post" action="user.cgi">
<input type="hidden" name="user" value="%s">
Initialize %s watching these bills:
<input type="text" name="bills" size=45 value="%s">
<p>
<input type="submit" name="Confirm"
       value="Confirm new user %s">''' % (username, username, username,
                                          billstring, username))

    else:
        # No username specified. Let the user tell us who to use.
        header("New Mexico Bill Tracker: Add or Edit User")
        # print("no user CGI:", form)

        print('''<h2>Add a new user, or edit a current one</h2>
<form method="post" action="user.cgi">
Username:
<input type="text" name="user" size=20>
<p>
New bills to track (comma or space separated):
<input type="text" name="bills" size=45 value=%s>
<p>
<input type="submit" name="Update" value="Edit user">''' % billstring)

    # Close the form and the page regardless of which path we took.
    print('</form>')
    footer()

if __name__ == '__main__':
    if __file__.endswith("user.cgi"):
        user_page()
    else:
        bills_page()




