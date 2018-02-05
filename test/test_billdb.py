#!/usr/bin/env python3

import unittest
import datetime
import dateutil.parser

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billdb

class TestBillDB(unittest.TestCase):

    def populate(self):
        billdb.update_bill('SB83', dateutil.parser.parse("01/01/2018 14:25"))
        billdb.update_bill('SJM6', dateutil.parser.parse("2018-01-10 12:20"))
        billdb.update_bill('SB83', dateutil.parser.parse("2018-01-18 09:30"))

        billdb.update_user(email="user@example.com")
        billdb.update_user(email="someone@example.com")
        billdb.update_user("user@example.com", bills="SB83,SJM6")

    def test(self):
        try:
            os.unlink('testdb.sqlite')
        except:
            pass

        billdb.init(alternate_db="testdb.sqlite")
        self.populate()

        bills = billdb.get_user_bills("user@example.com")
        self.assertEqual(bills, ['SB83', 'SJM6'])
        bills = billdb.get_user_bills("someone@example.com")
        self.assertEqual(bills, None)

        print(billdb.all_bills())

        # billdb.update_and_quit()

