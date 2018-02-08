#!/usr/bin/env python

from __future__ import print_function

# Create a database with test users and their bills.
# We'll worry about running from cron later.

import billdb

import os
import datetime
import dateutil.parser

def init_test_user(email, bill_list):
    '''Create a new user with bill_list being a comma/space separated
       list of bill IDs.
    '''
    print("Initializing user %s" % email)
    for bill in bill_list.split(','):
        billdb.update_bill(bill, dateutil.parser.parse("01/01/2018 01:00"))

    billdb.update_user(email, bills=bill_list,
                       last_check=dateutil.parser.parse("01/01/2018 01:00"))

if __name__ == '__main__':
    now = datetime.datetime.now()

    try:
        os.unlink("bills.sqlite")
    except:
        pass

    billdb.init()

    init_test_user('user@example.com',
                   'HB16,SB19,HB59,HM9,SM2,HB38,HB95,SB39,HB158')

    billdb.commit_and_quit()


