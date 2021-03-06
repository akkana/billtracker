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

from billtracker.bills import nmlegisbill, billutils, billrequests

import datetime

class TestNMlegisbill(unittest.TestCase):

    def setUp(self):
        # Don't go to the actual nmlegis site
        billrequests.LOCAL_MODE = True
        billrequests.CACHEDIR = 'test/cache'

        # Uncomment to get verbose information on cache/net requests:
        # billrequests.DEBUG = True
        billrequests.CACHEDIR = 'test/cache'

    def tearDown(self):
        pass

    def test_parse_bills(self):
        # To see large diffs, set this:
        self.maxDiff = None

        # Don't go to the actual nmlegis site
        billrequests.LOCAL_MODE = True
        billrequests.CACHEDIR = 'test/cache'

        bill = nmlegisbill.parse_bill_page('HB73', yearcode='19')
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
                           'sponsor': 'HGONZ',
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
        bill = nmlegisbill.parse_bill_page('SB11', yearcode='19')
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
                          'sponsor': 'SCISN,SMARR,HCHAN,HROAN',
                          'sponsorlink': 'https://www.nmlegis.gov/Members/Legislator?SponCode=SCISN',
                          'statusHTML': '<span class="list-group-item" '
                          'id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_10"><b>Signed '
                          'by Governor - Chapter 44 - Feb. 28</b></span>',
                          'statustext':
                              '''Signed by Governor - Chapter 44 - Feb. 28
SPREF [1] SCORC/SFC-SCORC [3] DP-SFC [5] DP  [7] PASSED/S (29-6) [5] HTRC-HTRC [8] DP - fl/a- PASSED/H (64-0) [14] s/cncrd [15] SGND BY GOV (Feb. 28) Ch. 44.''',
                          'title': 'GROSS RECEIPTS FOR NONPROFIT ORGANIZATIONS',
                          'year': '19'})

        hhhc = nmlegisbill.expand_committee("HHHC")
        self.assertEqual(hhhc, {
            'chair': 'HARMS',
            'code': 'HHHC',
            'members': ['HARMS', 'HFERJ', 'HANDP', 'HARMG',
                        'HBABR', 'HBASH', 'HLORD', 'HMATT',
                        'HMORO', 'HTERR', 'HTHOE'],
            'mtg_time': 'Monday, Wednesday & Friday- 8:30 a.m. (Room 315)',
            'name': 'House Health & Human Services',
            'scheduled_bills': [
                ['SB96', datetime.datetime(2021, 3, 1, 8, 30)],
                ['SB27', datetime.datetime(2021, 3, 1, 8, 30)],
                ['HB305', datetime.datetime(2021, 3, 1, 8, 30)],
                ['HB284', datetime.datetime(2021, 3, 1, 8, 30)],
                ['HB272', datetime.datetime(2021, 2, 26, 8, 30)],
                ['HB269', datetime.datetime(2021, 2, 26, 8, 30)],
                ['HB250', datetime.datetime(2021, 2, 26, 8, 30)],
                ['HB209', datetime.datetime(2021, 2, 26, 8, 30)],
                ['HB151', datetime.datetime(2021, 3, 1, 8, 30)] ]
        })

        sirc = nmlegisbill.expand_committee("SIRC")
        self.assertEqual(sirc, {
            'chair': 'SPINS',
            'code': 'SIRC',
            'members': ['SPINS', 'SJARA', 'SGRIG', 'SMCKE', 'SSANJ', 'SSHEN'],
            'mtg_time': 'Tuesday & Thursday - 9:00 a.m. (Room 303)',
            'name': 'Senate Indian, Rural & Cultural Affairs',
            'scheduled_bills': [['SB361', datetime.datetime(2021, 2, 16, 9, 0)],
                                ['SB332', datetime.datetime(2021, 2, 16, 9, 0)]]})

    def test_parse_datetimes(self):
        datestr, hour, minute = nmlegisbill.parse_comm_datetime("4:15 pm")
        self.assertEqual(datestr, "")
        self.assertEqual(hour, 16)
        self.assertEqual(minute, 15)

        datestr, hour, minute = nmlegisbill.parse_comm_datetime("4: 15 pm")
        self.assertEqual(datestr, "")
        self.assertEqual(hour, 16)
        self.assertEqual(minute, 15)

        datestr, hour, minute = nmlegisbill.parse_comm_datetime("Sometime around 4:15")
        self.assertEqual(datestr, "Sometime around")
        self.assertEqual(hour, 16)
        self.assertEqual(minute, 15)

        datestr, hour, minute = nmlegisbill.parse_comm_datetime("LALALA4:15plus some other stuff")
        self.assertEqual(datestr, "LALALA")
        self.assertEqual(hour, 16)
        self.assertEqual(minute, 15)

        datestr, hour, minute = nmlegisbill.parse_comm_datetime("Thursday, February 25, 2021  -  1:30 or 15 minutes after floor session")
        self.assertEqual(datestr, "Thursday, February 25, 2021")
        self.assertEqual(hour, 13)
        self.assertEqual(minute, 30)

        datestr, hour, minute = nmlegisbill.parse_comm_datetime("Tuesday & Thursday -1:30 p.m. (Room 321)")
        self.assertEqual(datestr, "Tuesday & Thursday")
        self.assertEqual(hour, 13)
        self.assertEqual(minute, 30)

        datestr, hour, minute = nmlegisbill.parse_comm_datetime("Wednesday, February 24, 2021  -  9:00 a.m.  -  Room")
        self.assertEqual(datestr, "Wednesday, February 24, 2021")
        self.assertEqual(hour, 9)
        self.assertEqual(minute, 0)

        datestr, hour, minute = nmlegisbill.parse_comm_datetime("Monday, Wednesday & Friday - 9:00 a.m. (Room 321)")
        self.assertEqual(datestr, "Monday, Wednesday & Friday")
        self.assertEqual(hour, 9)
        self.assertEqual(minute, 0)


