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

print('''Content-type: text/html

<html>
<head>
<title>New Mexico Bill Tracker</title>
<style type="text/css">
  table { border-collapse: collapse; }
  table.bill th, table.bill td { border: 2px solid #bbc; }
  dd { font-weight: bold; }
  tr.header th { background: lightblue; }
</style>
</head>

<body>
<h1>New Mexico Bill Tracker</h1>
''')

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

form = cgi.FieldStorage()

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

print("</body></html>")


