#!/usr/bin/env python

from __future__ import print_function

import sqlite3
# https://docs.python.org/3/library/sqlite3.html

import datetime, dateutil.parser
import sys
import re

dbconn = None
cursor = None
dbname = "./bills.sqlite"

billfields = [ 'billno', 'mod_date', 'bill_url',
               'chamber', 'billtype', 'number', 'year',
               'title', 'contents_url', 'status', 'statuslink', 'statustext',
               'sponsor', 'sponsorlink', 'curloc', 'curloclink',
               'FIRlink', 'LESClink', 'last_action_date'
             ]
# Most fields are strings, which is the default, so use None for that.
billfield_types = [ None, 'timestamp', None, None, None, None, None, None,
                    None, None, None, None, None, None, None, None, None,
                    None, 'timestamp' ]

userfields = [ 'email', 'password', 'auth_code',
               'bills', 'last_check'
             ]
userfield_types = [ None, None, None, None, 'timestamp' ]

primary_keys = { 'bills': 'billno', 'users': 'email' }

#
# Utilities to translate between Python dictionaries and sqlite3.
#

# Use a dictionary row factory so the data we retrieve from the db
# has columns labeled and we don't need to worry about order.
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def create_dict_table(tablename, fields, fieldtypes):
    # Run something like this:
    # cursor.execute('CREATE TABLE users (field1, field2 type, field3)'
    fieldstrings = []
    for i, field in enumerate(fields):
        if fieldtypes[i]:
            fieldstrings.append('%s %s' % (field, fieldtypes[i]))
        else:
            fieldstrings.append(field)

    cursor.execute('CREATE TABLE %s (%s)' % (tablename,
                                             ', '.join(fieldstrings)))

# Alas, factories don't help in inserting or changing items in the database.
# Have to write that manually.
def dict_into_db(obj, tablename):

    # Is it aready in the database?
    if exists_in_db(obj[primary_keys[tablename]], tablename):
        # When updating an existing row, sqlite wants
        # col1 = ?, col2 = ? syntax.
        setcolumns = ', '.join([ "%s = ?" % v for v in obj.keys()])
        sql = "UPDATE %s SET %s WHERE %s = ?" % (tablename, setcolumns,
                                                 primary_keys[tablename])
        vals = list(obj.values()) + [obj[primary_keys[tablename]]]
        cursor.execute(sql, vals)

    else:
        # When adding a new row, sqlite3 wants col1, col2 = ?, ? syntax
        columns = ', '.join(obj.keys())
        placeholders = ', '.join('?' * len(obj))
        sql = 'INSERT INTO %s (%s) VALUES (%s)' % (tablename,
                                                   columns, placeholders)
        cursor.execute(sql, list(obj.values()))

#
# End dictionary utilities
#

def init(alternate_db=None):
    global dbname, dbconn, cursor

    if alternate_db:
        dbname = alternate_db

    # Connect to the db. This will create the file if it isn't already there.
    try:
        dbconn = sqlite3.connect(dbname, detect_types=sqlite3.PARSE_DECLTYPES)
        dbconn.row_factory = dict_factory

    except sqlite3.OperationalError:
        print("Can't create database file %s" % dbname)
        sys.exit(1)

    # sqlite needs a "cursor" to access the database.
    cursor = dbconn.cursor()

    # Make sure we have the bill table.
    # This is the only part we keep in the fixed database;
    # everything else is updated from nmlegis.gov web pages.
    try:
        create_dict_table("users", userfields, userfield_types)
        create_dict_table("bills", billfields, billfield_types)
        dbconn.commit()

    except sqlite3.OperationalError:
        pass

# sqlite apparently has no real way to test for existence.
def exists_in_db(key, table):
    cursor.execute("SELECT %s from %s WHERE %s=?" % (primary_keys[table],
                                                     table,
                                                     primary_keys[table]),
                   (key,))
    data = cursor.fetchone()
    if data is None:
        return False
    return True

def commit():
    dbconn.commit()
    print("Updated database", file=sys.stderr)

def commit_and_quit():
    dbconn.commit()
    dbconn.close()
    print("Updated database")
    sys.exit(0)

#
# Functions relating to bills:
#

def fetch_bill(billno):
    cursor.execute("SELECT * from bills WHERE billno=?", (billno,))
    return cursor.fetchone()

def all_bills():
    '''Return a list of all the bills in the database.'''

    cursor.execute("SELECT * from bills")
    return cursor.fetchall()

def update_bill(bill, date=None):
    '''Update a bill, which is either a billno as a string, like "SB1",
       or a dictionary containing all bill values.
    '''
    if not bill:
        return
    if isinstance(bill, dict):
        if date:
            bill["mod_date"] = date
        dict_into_db(bill, "bills")
        return

    if exists_in_db(bill, "bills"):
        cursor.execute("UPDATE bills SET mod_date = ? WHERE billno = ?",
                       (date, bill))
    else:
        # How many fields are there in bills?
        placeholders = ', '.join('?' * len(billfields))
        # vals has bill and date as the first two fields, None elsewhere
        vals = [ bill, date ] + ([ None ] * (len(billfields) - 2))
        cursor.execute("INSERT INTO bills VALUES (%s)" % placeholders, vals)

#
# Functions relating to users:
# Users have: email, password, auth_code, bills, last_check
#

def update_user(email, bills=None, last_check=None):
    '''Add or update a user.
       last_check is a datetime; now if not specified.
       If email or bills is None, will leave that field unchanged.

    '''

    if not email:
        raise RuntimeError("update_user with no user")
        return

    # Is it a new user?
    cursor.execute("SELECT * from users WHERE email=?", (email,))
    data  = cursor.fetchone()
    if data is None:
        if not last_check:
            last_check = datetime.datetime.now()

        # How many fields are there in users?
        placeholders = ', '.join('?' * len(userfields))
        vals = (email, None, None, bills, last_check)
        cursor.execute("INSERT INTO users VALUES (%s)" % placeholders, vals)
        return

    # The user already exists.
    # Guard against empty updates, but check explicitly for None:
    # allow changing bills to ''.
    if bills == None and last_check == None:
        print("update_user %s with nothing to update" % email)
        return

    # Update what we can. Don't change last_check unless it was specified.
    if bills != None:
        cursor.execute('UPDATE users SET bills = ? WHERE email=?',
                       (bills, email))
    if last_check:
        cursor.execute('UPDATE users SET last_check = ? WHERE email=?',
                       (last_check, email))
    # dbconn.commit()

def all_users():
    '''Return a list of all users in the database.'''

    cursor.execute("SELECT * from users")
    return cursor.fetchall()

def get_user_bills(email):
    cursor.execute("SELECT bills FROM users WHERE email = ?", (email,))

    # fetchone() returns a tuple even though it's explicitly
    # asking for only one. Go figure.
    bills = cursor.fetchone()
    if not bills:
        return None
    if bills['bills']:
        # Bills may be either comma or whitespace separated.
        sep = re.compile('[,\s]+')
        return sep.split(bills['bills'])
    return None

def set_user_bills(email, bills):
    cursor.execute("UPDATE users SET bills WHERE email = ?", (email, bills))
    dbconn.commit()

if __name__ == '__main__':
    init()

    bill = { 'billno': 'HJR22',
             'mod_date': dateutil.parser.parse("01/09/2018 10:32")
    }
    dict_into_db(bill, "bills")

    print(all_bills())

    cursor.execute("SELECT email,bills FROM users")
    bills_users = cursor.fetchall()
    for userdic in bills_users:
        print("%s bills: %s" % (userdic["email"], userdic["bills"]))

    # commit_and_quit()

def user_bill_summary(user):
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
        billdic = fetch_bill(billno)
        analysisText = ''
        analysisHTML = ''
        if billdic['FIRlink']:
            analysisText += '  FIR: ' + billdic['FIRlink'] + '\n'
            analysisHTML += '<a href="%s">FIR report</a>' % billdic['FIRlink']
        if billdic['LESClink']:
            analysisText += '  LESC: ' + billdic['LESClink'] + '\n'
            analysisHTML += '<a href="%s">LESC report</a>' % billdic['LESClink']
        if billdic['FIRlink'] or billdic['LESClink']:
            analysisHTML += '<br />'

        if billdic['mod_date'] > last_check:
            newertext += '''
%s %s .. updated %s
  Bill page: %s
  Bill text: %s
  Analysis: %s
  History:
%s''' % (billno, billdic['title'], billdic['mod_date'].strftime('%m/%d/%Y'),
         billdic['bill_url'], billdic['contents_url'], analysisText,
         billdic['statustext'])
            newerhtml += '''<p>
<div class="%s">
<a href="%s">%s: %s</a> .. updated %s<br />
  <a href="%s">Text of bill</a><br />
  %s
  History:
%s
</div>''' % ("even" if even else "odd",
             billdic['bill_url'], billno, billdic['title'],
             billdic['mod_date'].strftime('%m/%d/%Y'),
             billdic['contents_url'], analysisHTML, billdic['status'])

        else:
            oldertext += "\n%s %s .. %s" % (billno, billdic['title'],
                                               billdic['mod_date'])
            olderhtml += '<br /><a href="%s">%s %s</a> .. last updated %s' % \
                        (billdic['bill_url'], billno, billdic['title'],
                         billdic['mod_date'])

    return (newerhtml + olderhtml + '</body></html>',
            newertext + "\n===============\n" + oldertext)
