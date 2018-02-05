#!/usr/bin/env python

import sqlite3
# https://docs.python.org/3/library/sqlite3.html

import datetime
import sys
import re

dbconn = None
cursor = None
dbname = "./bills.sqlite"

# Use a dictionary row factory so the data we retrieve from the db
# has columns labeled and we don't need to worry about order.
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

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
        cursor.execute('''CREATE TABLE users (email, password, auth_code, bills, last_check timestamp)''')
        print("Added user table")
        cursor.execute('''CREATE TABLE bills (billno, mod_date)''')
        print("Added bills table")

        dbconn.commit()

    except sqlite3.OperationalError:
        pass

# sqlite apparently has no real way to test for existence.
def exists_in_db(key, table):
    if table == "bills":
        cursor.execute("SELECT * from bills WHERE billno=?", (key,))
    elif table == "users":
        cursor.execute("SELECT * from users WHERE username=?", (key,))
    else:
        return False
    data = cursor.fetchone()
    if data is None:
        return False
    return True

def update_and_quit():
    dbconn.commit()
    dbconn.close()
    print("Updated database")
    sys.exit(0)

#
# Functions relating to bills:
#

def all_bills():
    '''Return a list of all the bills in the database.'''

    cursor.execute("SELECT * from bills")
    return cursor.fetchall()

def update_bill(billno, date):
    if exists_in_db(billno, "bills"):
        cursor.execute("UPDATE bills SET mod_date = ? WHERE billno = ?",
                       (date, billno))
    else:
        cursor.execute("INSERT INTO bills VALUES (?, ?)", (billno, date))

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
        cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                       (email, "", "", "", last_check))
        return

    # The user already exists.
    # Guard against empty updates, but check explicitly for None:
    # allow changing bills to ''.
    if bills == None and last_check == None:
        print("update_user %s with nothing to update" % email)
        return

    # Update what we can. Don't change last_check unless it was specified.
    setters = []
    vals = []
    if bills != None:
        setters.append("bills=?")
        vals.append(bills)
    if last_check:
        setters.append("last_check=?")
        vals.append(last_check)

    vals.append(email)

    cursor.execute('UPDATE users SET %s WHERE email=?' % ', '.join(setters),
                   vals)
    dbconn.commit()

def all_users():
    '''Return a list of all users in the database.'''

    cursor.execute("SELECT * from users")
    return cursor.fetchall()

def get_user_bills(email):
    cursor.execute("SELECT bills FROM users WHERE email = ?", (email,))

    # fetchone() returns a tuple even though it's explicitly
    # asking for only one. Go figure.
    bills = cursor.fetchone()
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

    print(all_bills())

    cursor.execute("SELECT username,bills FROM users")
    bills_users = cursor.fetchall()
    for userdic in bills_users:
        print("%s bills: %s" % (userdic["username"], userdic["bills"]))

    # update_and_quit()
