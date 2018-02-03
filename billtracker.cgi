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
    print("<p>User: %s is tracking bills:" % form['user'].value)

    billdb.init()

    bills = billdb.get_user_bills("testuser")
    for bill in bills:
        print("<p>", bill)
        billdic = nmlegisbill.parse_bill_page(bill)
        for key in billdic:
            print("<br>\n &nbsp; &nbsp; %s: %s" % (key, billdic[key]))
else:
    print("Username?")

print("</body></html>")


