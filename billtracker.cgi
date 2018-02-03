#!/usr/bin/env python3

import cgi
# CGI tracebacks:
import cgitb
cgitb.enable()

import billdb
import nmlegisbill

print('''Content-type: text/html

<html>
<head>
<title>New Mexico Bill Tracker</title>
</head>

<body>
<h1>New Mexico Bill Tracker</h1>
''')

form = cgi.FieldStorage()
if "user" in form:
    print("<p>\nBills %s is tracking:" % form['user'].value)

    billdb.init()

    bills = billdb.get_user_bills("testuser")
    print("<dl>")
    for bill in bills:
        print("<dt>", bill)
        billdic = nmlegisbill.parse_bill_page(bill)
        for key in billdic:
            val = billdic[key]
            if key.endswith("url") or key.endswith("link"):
                print("<dd>%s: <a href='%s'>%s</a>" % (key, val, val))
            else:
                print("<dd>%s: %s" % (key, val))
    print("</dl>")
else:
    print("Username?")

print("</body></html>")


