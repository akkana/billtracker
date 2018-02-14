#!/usr/bin/env python

import unittest
import datetime
import dateutil.parser

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billdb

class TestBillDB(unittest.TestCase):

    def populate(self):
        bill = { 'billno': 'HJR22',
                 'mod_date': dateutil.parser.parse("01/09/2018 10:32")
        }
        billdb.dict_into_db(bill, "bills")

        billdb.update_bill('SB83', dateutil.parser.parse("01/01/2018 14:25"))
        billdb.update_bill('SJM6', dateutil.parser.parse("2018-01-10 12:20"))
        billdb.update_bill('SB83', dateutil.parser.parse("2018-01-18 09:30"))

        billdb.update_user(email="user@example.com")
        billdb.update_user(email="someone@example.com")

    def test(self):
        # To see long diffs:
        self.maxDiff = None

        try:
            os.unlink('testdb.sqlite')
        except:
            pass

        billdb.init(alternate_db="testdb.sqlite")
        self.populate()

        # Did we add the bills correctly?
        bill = billdb.fetch_bill('SB83')
        self.assertEqual(bill,
                         { 'bill_url': None,
                           'billno': u'SB83',
                           'chamber': None,
                           'billtype': None,
                           'number': None,
                           'contents_url': None,
                           'curloc': None,
                           'curloclink': None,
                           'mod_date': datetime.datetime(2018, 1, 18, 9, 30),
                           'sponsor': None,
                           'sponsorlink': None,
                           'statusHTML': None,
                           'statustext': None,
                           'year': None,
                           'FIRlink': None,
                           'LESClink': None,
                           'amendlink': None,
                           'last_action_date': None,
                           'update_date': None,
                           'title': None })

        bill = billdb.fetch_bill('SJM6')
        self.assertEqual(bill,
                         { 'billno': u'SJM6',
                           'bill_url': None,
                           'chamber': None,
                           'billtype': None,
                           'number': None,
                           'contents_url': None,
                           'curloc': None,
                           'curloclink': None,
                           'mod_date': datetime.datetime(2018, 1, 10, 12, 20),
                           'sponsor': None,
                           'sponsorlink': None,
                           'statusHTML': None,
                           'statustext': None,
                           'year': None,
                           'FIRlink': None,
                           'LESClink': None,
                           'amendlink': None,
                           'last_action_date': None,
                           'update_date': None,
                           'title': None })

        # Now change a bill:
        bill['title'] = "DUMMY BILL"
        billdb.update_bill(bill)

        # and fetch it and check the results:
        bill = billdb.fetch_bill('SJM6')
        self.assertEqual(bill,
                         { 'billno': u'SJM6',
                           'bill_url': None,
                           'chamber': None,
                           'billtype': None,
                           'number': None,
                           'contents_url': None,
                           'curloc': None,
                           'curloclink': None,
                           'mod_date': datetime.datetime(2018, 1, 10, 12, 20),
                           'sponsor': None,
                           'sponsorlink': None,
                           'statusHTML': None,
                           'statustext': None,
                           'year': None,
                           'FIRlink': None,
                           'LESClink': None,
                           'amendlink': None,
                           'last_action_date': None,
                           'update_date': None,
                           'title': 'DUMMY BILL' })

        # Did we add user bills correctly?
        bills = billdb.get_user_bills("user@example.com")
        self.assertEqual(bills, None)

        # Try adding some:
        billdb.update_user("user@example.com", bills="SB83,SJM6")
        bills = billdb.get_user_bills("user@example.com")
        self.assertEqual(bills, ['SB83', 'SJM6'])

        bills = billdb.get_user_bills("someone@example.com")
        self.assertEqual(bills, None)

        self.assertEqual(billdb.all_bills(),
                         [{'billno': 'HJR22', 'mod_date': datetime.datetime(2018, 1, 9, 10, 32), 'bill_url': None, 'chamber': None, 'billtype': None, 'number': None, 'year': None, 'title': None, 'contents_url': None, 'statusHTML': None, 'statustext': None, 'sponsor': None, 'sponsorlink': None, 'curloc': None, 'curloclink': None, 'FIRlink': None, 'LESClink': None,  'amendlink': None, 'last_action_date': None, 'update_date': None,},
                          {'billno': 'SB83', 'mod_date': datetime.datetime(2018, 1, 18, 9, 30), 'bill_url': None, 'chamber': None, 'billtype': None, 'number': None, 'year': None, 'title': None, 'contents_url': None, 'statusHTML': None, 'statustext': None, 'sponsor': None, 'sponsorlink': None, 'curloc': None, 'curloclink': None, 'FIRlink': None, 'LESClink': None,  'amendlink': None, 'last_action_date': None, 'update_date': None,},
                          {'billno': 'SJM6', 'mod_date': datetime.datetime(2018, 1, 10, 12, 20), 'bill_url': None, 'chamber': None, 'billtype': None, 'number': None, 'year': None, 'title': 'DUMMY BILL', 'contents_url': None, 'statusHTML': None, 'statustext': None, 'sponsor': None, 'sponsorlink': None, 'curloc': None, 'curloclink': None, 'FIRlink': None, 'LESClink': None, 'amendlink': None, 'last_action_date': None, 'update_date': None,}] )

        # billdb.commit_and_quit()

