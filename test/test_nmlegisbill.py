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
        del bill['mod_date']
        self.assertEqual(bill,
                         { 'billno': 'SB83',
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
                           'status': '\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_0"><br><strong>Sent to SPREF - Referrals: SPREF</strong></span>\n<br><br>\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_1">Legislative Day: 2<br/>Calendar Day: 01/18/2018<br><strong>Sent to SCC - Referrals: SCC/SPAC/SFC</strong></span>\n<br><br>\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_2">Legislative Day: 5<br/>Calendar Day: 01/22/2018<br><strong>SCC: Reported by committee to fall within the purview of a 30 day session</strong></span>\n<br><br>\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_3">Legislative Day: 9<br/>Calendar Day: 01/31/2018<br><strong>SPAC: Reported by committee with Do Pass recommendation</strong></span>\n',
                           'statustext': '    Sent to SPREF - Referrals: SPREF\n\n    Legislative Day: 2\n    Calendar Day: 01/18/2018\n    Sent to SCC - Referrals: SCC/SPAC/SFC\n\n    Legislative Day: 5\n    Calendar Day: 01/22/2018\n    SCC: Reported by committee to fall within the purview of a 30 day session\n\n    Legislative Day: 9\n    Calendar Day: 01/31/2018\n    SPAC: Reported by committee with Do Pass recommendation\n',
                           'contents_url': 'https://www.nmlegis.gov/Sessions/18%20Regular/bills/senate/SB0083.html'
                         })

        bill = nmlegisbill.parse_bill_page('HJR1', year=2018)
        del bill['mod_date']
        self.assertEqual(bill,
                         { 'billno': 'HJR1',
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
                           'status': '\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_0"><br><strong>Sent to HPREF - Referrals: HPREF</strong></span>\n<br><br>\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_1">Legislative Day: 1<br/>Calendar Day: 01/16/2018<br><strong>Sent to HEC - Referrals: HEC/HJC</strong></span>\n<br><br>\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_2">Legislative Day: 2<br/>Calendar Day: 01/24/2018<br><strong>HEC: Reported by committee with Do Pass recommendation with amendment(s)</strong></span>\n<br><br>\n<span class="list-group-item" id="MainContent_tabContainerLegislation_tabPanelActions_dataListActions_lblAction_3">Legislative Day: 3<br/>Calendar Day: 01/30/2018<br><strong>HJC: Reported by committee with Do Pass recommendation</strong></span>\n',
                           'statustext': '    Sent to HPREF - Referrals: HPREF\n\n    Legislative Day: 1\n    Calendar Day: 01/16/2018\n    Sent to HEC - Referrals: HEC/HJC\n\n    Legislative Day: 2\n    Calendar Day: 01/24/2018\n    HEC: Reported by committee with Do Pass recommendation with amendment(s)\n\n    Legislative Day: 3\n    Calendar Day: 01/30/2018\n    HJC: Reported by committee with Do Pass recommendation\n',
                           'title': 'LAND GRANT FUND DISTRIBUTIONS, CA',
                           'contents_url': 'https://www.nmlegis.gov/Sessions/18%20Regular/resolutions/house/HJR01.html'
                         })




