#!/usr/bin/env python3

import unittest

import sys, os
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from billtracker.bills.decodenmlegis import decode_full_history

from datetime import date

class TestNMlegisbill(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_locations(self):
        testpats = {
            "HPREF [2] HCPAC/HJC-HCPAC- DP-HJC [4] DP/a": {
                "location": "House",
                "lastaction": date(2023, 2, 7),
                "status": "Legislative Day: 4, Calendar Day: 02/07/2023, HJC: Reported by committee with Do Pass recommendation with amendment(s)",
                "histlist": [
                    (0, 'House Pre-file', 'HPREF'),
                    (2, 'Sent to HCPAC, ref HJC', 'HCPAC/HJC-HCPAC- DP-HJC'),
                    (4, 'Do Pass, as amended, committee report adopted.', 'DP/a')
                ],
            },
            "HPREF [2] HHHC/HAFC-HHHC": {
                "location": "HHHC",
                "lastaction": date(2023, 1, 18),
                "status": "Legislative Day: 2, Calendar Day: 01/18/2023, Sent to HHHC - Referrals: HHHC/HAFC",
                "histlist": [
                    (0, 'House Pre-file', 'HPREF'),
                    (2, 'Sent to HCPAC, ref HJC', 'HCPAC/HJC-HCPAC- DP-HJC'),
                    (4, 'Do Pass, as amended, committee report adopted.', 'DP/a')
                ]
            },
            "[1] HAFC-HAFC- DP [2] PASSED/H (47-19) [1] SFC-SFC- DP [2] PASSED/S (33-5)- SGND BY GOV (Jan. 20) Ch. 1.": {
                "location": "Signed",
                "lastaction": date(2023, 1, 20),
                "status": "",
                "histlist": [
                    (1, 'HAFC-HAFC- Do Pass committee report adopted.', 'HAFC-HAFC- DP'), (2, 'Passed House (47-19)', 'PASSED/H (47-19)'),
                    (1, 'SFC-SFC- Do Pass committee report adopted.', 'SFC-SFC- DP'),
                    (2, 'Passed Senate (33-5)- Signed by one or both houses (does not require Governor’s signature) BY GOV (Jan. 20) Ch. 1.', 'PASSED/S (33-5)- SGND BY GOV (Jan. 20) Ch. 1.')
                ]
            },
        }
        '''
            "x": {
                "location": "",
                "lastaction": "",
                "status": "",
                "histlist": [
                ]
            },
        '''
        for actiontext in testpats:
            location, status, histlist = \
                decode_full_history(actiontext)
            print("histlist:", histlist)
            # self.assertEqual(location, testpats[actiontext]["location"])
            # self.assertEqual(histlist, testpats[actiontext]["histlist"])

