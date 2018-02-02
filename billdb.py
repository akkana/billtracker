#!/usr/bin/env python3

import sqlite3
# https://docs.python.org/3/library/sqlite3.html

import datetime
import sys

dbconn = None
cursor = None
dbname = "./bills.sqlite"

def init():
    global dbconn, cursor
    # Connect to the db. This will create the file if it isn't already there.
    try:
        dbconn = sqlite3.connect(dbname)
    except sqlite3.OperationalError:
        print("Can't create database file %s" % dbname)
        sys.exit(1)

    # sqlite needs a "cursor" to access the database.
    cursor = dbconn.cursor()

    # Make sure we have the bill table.
    # This is the only part we keep in the fixed database;
    # everything else is updated from nmlegis.gov web pages.
    try:
        cursor.execute('''CREATE TABLE users (username, email, bills, last_check)''')
        print("Added user table")
        cursor.execute('''CREATE TABLE bills (billno, mod_date)''')
        print("Added bills table")
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

def update_bill(billno, date):
    if exists_in_db(billno, "bills"):
        cursor.execute("UPDATE bills SET mod_date = ? WHERE billno = ?",
                       (date, billno))
    else:
        cursor.execute("INSERT INTO bills VALUES (?, ?)", (billno, date))

#
# Functions relating to users:
#

def update_user(user, email=None, bills=None, last_check=None):
    '''Add or update a user.
       last_check is a datetime; now if not specified.
       If email or bills is None, will leave that field unchanged.
    '''

    # Is it a new user?
    cursor.execute("SELECT * from users WHERE username=?", (user,))
    data  = cursor.fetchone()
    if data is None:
        if not email:
            raise RuntimeError("Can't add a new user without email address")
        if not last_check:
            last_check = datetime.datetime.now()
        cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user, email,
                                                                 "",
                                                                 last_check))
        return

    # The user already exists. data = (user, email, bills, last_check).
    # Update what we can. Don't change last_check unless it was specified.
    setters = []
    vals = []
    if email:
        setters.append("email=?")
        vals.append(email)
    if bills:
        setters.append("bills=?")
        vals.append(bills)
    if last_check:
        setters.append("last_check=?")
        vals.append(last_check)
    vals.append(user)

    cursor.execute("UPDATE users SET %s WHERE username=?" % ', '.join(setters),
                   vals)
    print("Added setters", setters, "vals", vals)

def get_user_bills(user):
    cursor.execute("SELECT bills FROM users WHERE username = ?", (user,))

    # fetchone() returns a tuple even though it's explicitly asking
    # for only one. Go figure.
    bills = cursor.fetchone()[0]
    if bills:
        return bills.split(',')
    return None

#
# Functions just for testing:
#

def populate():
    update_bill('SB83', '2018-01-01')
    update_bill('SJM6', '2018-01-10')
    update_bill('SB83', '2018-01-18')
    update_user("testuser", email="user@example.com")
    update_user("someoneelse", email="someone@example.com")
    update_user("testuser", email="testuser@example.com")
    update_user("testuser", bills="SB83,SJM6")

if __name__ == '__main__':
    init()

    # populate()

    bills = get_user_bills("testuser")
    print("testuser's bills:", bills)
    bills = get_user_bills("someoneelse")
    print("someone else's bills:", bills)

    update_and_quit()
