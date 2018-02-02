#!/usr/bin/env python3

import sqlite3
# https://docs.python.org/3/library/sqlite3.html

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
        cursor.execute('''CREATE TABLE bills (billno, mod_date)''')
    except sqlite3.OperationalError:
        print("The table already exists")

def update_and_quit():
    dbconn.commit()
    dbconn.close()
    sys.exit(0)

def print_all_bills():
    for b in cursor.execute("SELECT * FROM bills"):
        print(b)

def print_bill(billno):
    cursor.execute("SELECT * FROM bills WHERE billno=?", (billno,))
    billno, date = cursor.fetchone()
    print(billno, date)

def add_bill(billno, date):
    cursor.execute("INSERT INTO bills VALUES (?, ?)", (billno, date))

def update_bill_date(billno, date):
    cursor.execute("UPDATE bills SET mod_date = ? WHERE billno = ?",
                   (date, billno))

if __name__ == '__main__':
    init()

    # update_bill_date('SB83', '2018-01-01')
    # update_and_quit()

    if len(sys.argv) > 1:
        for n in sys.argv[1:]:
            print_bill(n)
    else:
        print_all_bills()
