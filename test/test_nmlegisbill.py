#!/usr/bin/env python3

# This set of tests gives a warning from lxml:
# /usr/lib/python3/dist-packages/bs4/builder/_lxml.py:250: DeprecationWarning: inspect.getargspec() is deprecated, use inspect.signature() or inspect.getfullargspec()
#   self.parser.feed(markup)

# The bug where it's deprecated seems to be https://bugs.python.org/issue20438
# It's discussed in zillions of project forums because apparently it broke
# unit tests all over -- see for instance this astropy discussion,
# https://github.com/astropy/astropy/issues/6301
# but I'm not clear from reading that how I can use lxml and bs4
# in unit tests without hitting the warning.

import unittest

import sys, os
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from billtracker.bills import nmlegisbill, billutils

import datetime

class TestNMlegisbill(unittest.TestCase):

    def setUp(self):
        nmlegisbill.cachedir = 'test/cache'


    def tearDown(self):
        pass


    def test_parse_bills(self):

        # To see large diffs, set this:
        self.maxDiff = None

        bill = nmlegisbill.parse_bill_page('HB73', year=2019, cachesecs=-1)
        # mod date keeps changing. Don't try to test it.
        bill['mod_date'] = None
        bill['update_date'] = None
        self.assertEqual(bill,
                         { 'billno': 'HB73',
                           'mod_date': None,
                           'update_date': None,
                           'chamber': 'H',
                           'billtype': 'B',
                           'number': '73',
                           'year': '19',
                           'title': 'EXEMPT NM FROM DAYLIGHT SAVINGS TIME',
                           'sponsor': 'Roberto "Bobby" J. Gonzales',
                           'sponsorlink': 'https://www.nmlegis.gov/Members/Legislator?SponCode=HGONZ',
                           'curloc': 'HJC',
                           'statusHTML': '<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_2">Legislative Day: 3<br/>Calendar Day: 01/29/2019<br><strong>HSEIC: Reported by committee with Do Pass recommendation with amendment(s)</strong></span>',
                           'statustext': '''Legislative Day: 3
    Calendar Day: 01/29/2019
    HSEIC: Reported by committee with Do Pass recommendation with amendment(s)
HPREF [2] HSEIC/HJC-HSEIC [3] DP/a-HJC''',
                           'last_action_date': datetime.datetime(2019, 1, 29, 0, 0),
                           'FIRlink': None,
                           'LESClink': None,
                           'amendlink': 'https://www.nmlegis.gov/Sessions/19%20Regular/Amendments_In_Context/HB0073.pdf',
                           'contentslink': 'https://www.nmlegis.gov/Sessions/19%20Regular/bills/house/HB0073.html'
                         })

        # Another bill, to make sure bills with no curloclink work:
        bill = nmlegisbill.parse_bill_page('SB11', year=2019, cachesecs=-1)
        bill['mod_date'] = None
        bill['update_date'] = None
        self.assertEqual(bill,
                         {'FIRlink': None,
                          'LESClink': None,
                          'amendlink': 'https://www.nmlegis.gov/Sessions/19%20Regular/Amendments_In_Context/SB0011.pdf',
                          'billno': 'SB11',
                          'billtype': 'B',
                          'chamber': 'S',
                          'contentslink': 'https://www.nmlegis.gov/Sessions/19%20Regular/bills/senate/SB0011.html',
                          'curloc': 'Chaptered',
                          'last_action_date': None,
                          'mod_date': None,
                          'update_date': None,
                          'number': '11',
                          'sponsor': 'Carlos R. Cisneros',
                          'sponsorlink': 'https://www.nmlegis.gov/Members/Legislator?SponCode=SCISN',
                          'statusHTML': '<span class="list-group-item" '
                          'id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_10"><b>Signed '
                          'by Governor - Chapter 44 - Feb. 28</b></span>',
                          'statustext':
                              '''Signed by Governor - Chapter 44 - Feb. 28
SPREF [1] SCORC/SFC-SCORC [3] DP-SFC [5] DP  [7] PASSED/S (29-6) [5] HTRC-HTRC [8] DP - fl/a- PASSED/H (64-0) [14] s/cncrd [15] SGND BY GOV (Feb. 28) Ch. 44.''',
                          'title': 'GROSS RECEIPTS FOR NONPROFIT ORGANIZATIONS',
                          'year': '19'})


