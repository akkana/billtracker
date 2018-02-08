#!/usr/bin/env python

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
import datetime

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nmlegisbill

nmlegisbill.url_mapper = nmlegisbill.LocalURLmapper('https://www.nmlegis.gov')

class TestNMlegisbill(unittest.TestCase):

    def test(self):

        # To see large diffs, set this:
        self.maxDiff = None

        bill = nmlegisbill.parse_bill_page('SB83', year=2018)
        # mod date keeps changing. Don't try to test it.
        bill['mod_date'] = None
        bill['update_date'] = None
        self.assertEqual(bill,
                         { 'billno': 'SB83',
                           'mod_date': None,
                           'update_date': None,
                           'chamber': 'S',
                           'billtype': 'B',
                           'number': '83',
                           'year': '18',
                           'bill_url': './test/2018-SB83.html',
                           'title': 'SUNSHINE PORTAL AUDIT & COMPLIANCE',
                           'sponsor': 'Sander Rue',
                           'sponsorlink': 'http://www.nmlegis.gov/Members/Legislator?SponCode=SSRUE',
                           'curloc': 'Senate Finance Committee',
                           'curloclink': 'https://www.nmlegis.gov/Committee/Standing_Committee?CommitteeCode=SFC',
                           'statusHTML': '<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_3">Legislative Day: 9<br/>Calendar Day: 01/31/2018<br><strong>SPAC: Reported by committee with Do Pass recommendation</strong></span>',
                           'statustext': '    Legislative Day: 9\n    Calendar Day: 01/31/2018\n    SPAC: Reported by committee with Do Pass recommendation',
                           'last_action_date': datetime.datetime(2018, 1, 31, 0, 0),
                           'FIRlink': None,
                           'LESClink': None,
                           'contents_url': 'https://www.nmlegis.gov/Sessions/18%20Regular/bills/senate/SB0083.html'
                         })

        bill = nmlegisbill.parse_bill_page('HJR1', year=2018)
        bill['mod_date'] = None
        bill['update_date'] = None
        self.assertEqual(bill,
                         { 'billno': 'HJR1',
                           'mod_date': None,
                           'update_date': None,
                           'chamber': 'H',
                           'billtype': 'JR',
                           'number': '1',
                           'year': '18',
                           'bill_url': './test/2018-HJR1.html',
                           'title': 'LAND GRANT FUND DISTRIBUTIONS, CA',
                           'sponsor': 'Antonio "Moe" Maestas',
                           'sponsorlink': 'http://www.nmlegis.gov/Members/Legislator?SponCode=HMAES',
                           'curloc': 'House Calendar',
                           'curloclink': 'https://www.nmlegis.gov/Entity/House/Floor_Calendar',
                           'statusHTML': '<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_3">Legislative Day: 3<br/>Calendar Day: 01/30/2018<br><strong>HJC: Reported by committee with Do Pass recommendation</strong></span>',
                           'statustext': '    Legislative Day: 3\n    Calendar Day: 01/30/2018\n    HJC: Reported by committee with Do Pass recommendation',
                           'title': 'LAND GRANT FUND DISTRIBUTIONS, CA',
                           'last_action_date': datetime.datetime(2018, 1, 30, 0, 0),
                           'FIRlink': None,
                           'LESClink': None,
                           'contents_url': 'https://www.nmlegis.gov/Sessions/18%20Regular/resolutions/house/HJR01.html'
                         })


