#!/usr/bin/env python3

import unittest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billdb

class TestBillDB(unittest.TestCase):

    def populate():
        billdb.update_bill('SB83', '2018-01-01')
        billdb.update_bill('SJM6', '2018-01-10')
        billdb.update_bill('SB83', '2018-01-18')
        billdb.update_user("testuser", email="user@example.com")
        billdb.update_user("someoneelse", email="someone@example.com")
        billdb.update_user("testuser", email="testuser@example.com")
        billdb.update_user("testuser", bills="SB83,SJM6")

    def test(self):
        billdb.init(alternate_db="testdb.sqlite")
        TestBillDB.populate()

        bills = billdb.get_user_bills("testuser")
        self.assertEqual(bills, ['SB83', 'SJM6'])
        bills = billdb.get_user_bills("someoneelse")
        self.assertEqual(bills, None)

        # billdb.update_and_quit()

