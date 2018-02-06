#!/usr/bin/env python3

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
                           'status': None,
                           'statuslink': None,
                           'statustext': None,
                           'year': None,
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
                           'status': None,
                           'statuslink': None,
                           'statustext': None,
                           'year': None,
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
                           'status': None,
                           'statuslink': None,
                           'statustext': None,
                           'year': None,
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
                         [{'billno': u'HJR22', 'status': None, 'statuslink': None, 'curloclink': None, 'title': None, 'statustext': None, 'year': None, 'sponsorlink': None, 'number': None, 'sponsor': None, 'chamber': None, 'bill_url': None, 'mod_date': datetime.datetime(2018, 1, 9, 10, 32), 'curloc': None, 'contents_url': None, 'billtype': None}, {'billno': u'SB83', 'status': None, 'statuslink': None, 'curloclink': None, 'title': None, 'statustext': None, 'year': None, 'sponsorlink': None, 'number': None, 'sponsor': None, 'chamber': None, 'bill_url': None, 'mod_date': datetime.datetime(2018, 1, 18, 9, 30), 'curloc': None, 'contents_url': None, 'billtype': None}, {'billno': u'SJM6', 'status': None, 'statuslink': None, 'curloclink': None, 'title': u'DUMMY BILL', 'statustext': None, 'year': None, 'sponsorlink': None, 'number': None, 'sponsor': None, 'chamber': None, 'bill_url': None, 'mod_date': datetime.datetime(2018, 1, 10, 12, 20), 'curloc': None, 'contents_url': None, 'billtype': None}] )

        # billdb.commit_and_quit()

