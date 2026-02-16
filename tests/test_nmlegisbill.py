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

from app.bills import nmlegisbill, billutils, billrequests, decodenmlegis

import json

import datetime


billrequests.LOCAL_MODE = True
billrequests.CACHEDIR = 'tests/cache'

# Uncomment to get verbose information on cache/net requests:
# billrequests.DEBUG = True


def test_parse_bills():
    # Don't go to the actual nmlegis site
    billrequests.LOCAL_MODE = True
    billrequests.CACHEDIR = 'tests/cache'

    bill = nmlegisbill.parse_bill_page('HB73', yearcode='19')
    # mod date keeps changing. Don't try to test it.
    bill['mod_date'] = None
    bill['update_date'] = None
    assert bill == {
        'billno': 'HB73',
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
    }

    # Another bill, to make sure bills with no curloclink work:
    bill = nmlegisbill.parse_bill_page('SB11', yearcode='19')
    bill['mod_date'] = None
    bill['update_date'] = None
    assert bill == {
        'FIRlink': None,
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
        'year': '19' }

    hhhc = nmlegisbill.expand_committee("HHHC")
    assert hhhc == {
        'chair': 'HARMS',
        'code': 'HHHC',
        'members': ['HARMS', 'HFERJ', 'HANDP', 'HARMG',
                    'HBABR', 'HBASH', 'HLORD', 'HMATT',
                    'HMORO', 'HTERR', 'HTHOE'],
        'name': 'House Health & Human Services'
    }

    sirc = nmlegisbill.expand_committee("SIRC")
    assert sirc == {
        'chair': 'SPINS',
        'code': 'SIRC',
        'members': ['SPINS', 'SJARA', 'SGRIG', 'SMCKE', 'SSANJ', 'SSHEN'],
        'name': 'Senate Indian, Rural & Cultural Affairs'
    }


def test_decode_full_history():
    expected_file = "tests/files/actioncodes26-parsed.json"
    with open(expected_file) as fp:
        expected = json.load(fp)

    codes_file = "tests/files/actioncodes26.txt"
    # actual = []
    with open(codes_file) as fp:
        for line, actualobj in zip(fp, expected):
            yearbill, actioncode = line.split('|')
            yearcode, billno = yearbill.split()
            location, status, fullhist = \
                decodenmlegis.decode_full_history(actioncode)
            histdic = {
                'billno': billno,
                'yearcode': yearcode,
                'fullhist': fullhist,
                'location': location
            }
            assert histdic == actualobj
            # actual.append(histdic)

            # Print out everything, to allow manually eyeballing/checking
            # print("\n\n%s %s: %s" % (yearcode, billno, status))
            # print("  location:", location)
            # for day, longaction, code, location in fullhist:
            #     print("Day %s: %s (now in %s)" % (day, longaction, location))
            # pastloc, futureloc = decodenmlegis.get_location_lists(billno,
            #                                                       fullhist)
            # print("Past locations:", ' '.join(pastloc))
            # print("Future locations:", ' '.join(futureloc))

    # preparing the file to test against
    # with open(expected_file, 'w') as fp:
    #     json.dump(actual, fp, indent=2)
    #     print("Saved to", expected_file)


def test_parse_json_schedules():

    codelist = [ "HAAWC", "HCEDC", "HEC", "HGEIC", "HJC",
                 "HLVMC", "HTRC", "SFC", "SHPAC", "SIRC",
                 "SJC", "SRC", "STBTC"
                ]

    committee_sched = nmlegisbill.expand_committees(
        jsonsrc="tests/files/schedule-20220211.json")

    # Bill lists aren't necessarily in the same order every time,
    # so sort them in order to use assertEqual.
    for committee in committee_sched:
        for meeting in committee_sched[committee]['meetings']:
            meeting['bills'].sort()

    # from pprint import pprint
    # with open("/tmp/sched.json", "w") as fp:
    #     pprint(committee_sched, stream=fp)
    assert committee_sched == {
        'HAAWC': {'chair': 'HLENT',
                  'code': 'HAAWC',
                  'meetings': [],
                  'members': ['HLENT',
                              'HALLI',
                              'HBROW',
                              'HEZZE',
                              'HHOCH',
                              'HMATT',
                              'HSMAL',
                              'HZAMO'],
                  'name': 'House Agriculture, Acequias And Water Resources'},
        'HCEDC': {'code': 'HCEDC',
                  'meetings': [{'bills': ['HB228'],
                                'datetime': datetime.datetime(2022, 2, 11,
                                                              13, 30),
                                'timestr': '1:30 PM, room: 317, <a '
                                "href='https://us02web.zoom.us/j/88683384400' "
                                "target='_blank'>zoom link</a>, <a "
                                "href='https://nmlegis.gov/Agendas/Standing/hSched021122.pdf' "
                                "target='_blank'>PDF schedule</a>"}],
                  'members': ['HFIGU',
                              'HDOWR',
                              'HFAJA',
                              'HGADO',
                              'HHERN',
                              'HJOHD',
                              'HMARJ',
                              'HPOWD',
                              'HSERR'],
                  'name': 'House Commerce & Economic Development Committee'},
        'HEC': {'chair': 'HROMA',
                'code': 'HEC',
                'meetings': [{'bills': ['HM43', 'HM48', 'SB1', 'SB36'],
                              'datetime': datetime.datetime(2022, 2, 12, 9, 0),
                              'timestr': '9:00 AM, room: 309, <a '
                              "href='https://us02web.zoom.us/j/85200397115' "
                              "target='_blank'>zoom link</a>, <a "
                              "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                              "target='_blank'>PDF schedule</a>"},
                             {'bills': ['HM43', 'HM48', 'SB1', 'SB36'],
                              'datetime': datetime.datetime(2022, 2, 12, 9, 0),
                              'timestr': '9:00 AM, room: 309, <a '
                              "href='https://us02web.zoom.us/j/85200397115' "
                              "target='_blank'>zoom link</a>, <a "
                              "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                              "target='_blank'>PDF schedule</a>"}],
         'members': ['HROMA',
                     'HGARR',
                     'HBACB',
                     'HCHAT',
                     'HDOWR',
                     'HFIGU',
                     'HHERS',
                     'HLANE',
                     'HLARA',
                     'HMADR',
                     'HROYB',
                     'HSWEE',
                     'HTRCH'],
         'name': 'House Education'},
 'HGEIC': {'chair': 'HLOUI',
           'code': 'HGEIC',
           'meetings': [{'bills': ['HB181', 'HB193', 'HB6', 'HJM3', 'HJR14'],
                         'datetime': datetime.datetime(2022, 2, 12, 12, 0),
                         'timestr': '12:00 PM, room: 305, <a '
                                    "href='https://us02web.zoom.us/j/88201222358' "
                                    "target='_blank'>zoom link</a>, <a "
                                    "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                    "target='_blank'>PDF schedule</a>"},
                        {'bills': ['HB181', 'HB193', 'HB6', 'HJM3', 'HJR14'],
                         'datetime': datetime.datetime(2022, 2, 12, 12, 0),
                         'timestr': '12:00 PM, room: 305, <a '
                                    "href='https://us02web.zoom.us/j/88201222358' "
                                    "target='_blank'>zoom link</a>, <a "
                                    "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                    "target='_blank'>PDF schedule</a>"}],
           'members': ['HLOUI',
                       'HJOHD',
                       'HCHAS',
                       'HELYD',
                       'HGADO',
                       'HNIBE',
                       'HORTE',
                       'HREHM',
                       'HZAMO'],
           'name': 'House Government, Elections & Indian Affairs'},
 'HHHC': {'chair': 'HARMS',
          'code': 'HHHC',
          'meetings': [{'bills': ['HB239', 'SB138', 'SB38', 'SB40'],
                        'datetime': datetime.datetime(2022, 2, 11, 8, 30),
                        'timestr': '8:30 AM, room: 315, <a '
                                   "href='https://us02web.zoom.us/j/84182969724' "
                                   "target='_blank'>zoom link</a>, <a "
                                   "href='https://nmlegis.gov/Agendas/Standing/hSched021122.pdf' "
                                   "target='_blank'>PDF schedule</a>"}],
          'members': ['HARMS',
                      'HFERJ',
                      'HANDP',
                      'HARMG',
                      'HBABR',
                      'HBASH',
                      'HLORD',
                      'HMATT',
                      'HMORO',
                      'HTERR',
                      'HTHOE'],
          'name': 'House Health & Human Services'},
 'HJC': {'chair': 'HCHAS',
         'code': 'HJC',
         'meetings': [{'bills': ['HB145',
                                 'HB196',
                                 'HJR12',
                                 'HJR2',
                                 'SB144',
                                 'SB158',
                                 'SB159',
                                 'SB4',
                                 'SB43',
                                 'SJR3'],
                       'datetime': datetime.datetime(2022, 2, 12, 9, 0),
                       'timestr': '9:00 AM, room: 317, <a '
                                  "href='https://us02web.zoom.us/j/83315484306' "
                                  "target='_blank'>zoom link</a>, <a "
                                  "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                  "target='_blank'>PDF schedule</a>"},
                      {'bills': ['HB145',
                                 'HB196',
                                 'HJR12',
                                 'HJR2',
                                 'SB144',
                                 'SB158',
                                 'SB159',
                                 'SB4',
                                 'SB43',
                                 'SJR3'],
                       'datetime': datetime.datetime(2022, 2, 12, 9, 0),
                       'timestr': '9:00 AM, room: 317, <a '
                                  "href='https://us02web.zoom.us/j/83315484306' "
                                  "target='_blank'>zoom link</a>, <a "
                                  "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                  "target='_blank'>PDF schedule</a>"}],
         'members': ['HCHAS',
                     'HCADA',
                     'HALCO',
                     'HCHAN',
                     'HCOOK',
                     'HEGOL',
                     'HELYD',
                     'HLOUI',
                     'HMCQU',
                     'HNIBE',
                     'HREHM',
                     'HTOWJ'],
         'name': 'House Judiciary'},
 'HLVMC': {'chair': 'HALCO',
           'code': 'HLVMC',
           'meetings': [{'bills': ['HB243'],
                         'datetime': datetime.datetime(2022, 2, 12, 8, 30),
                         'timestr': '8:30 AM, room: 315, <a '
                                    "href='https://us02web.zoom.us/j/87484114766' "
                                    "target='_blank'>zoom link</a>, <a "
                                    "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                    "target='_blank'>PDF schedule</a>"}],
           'members': ['HALCO',
                       'HROYB',
                       'HBACB',
                       'HBASH',
                       'HBLAC',
                       'HBOUN',
                       'HDELA',
                       'HGAMP',
                       'HRUBI',
                       'HTERR'],
           'name': "House Labor, Veterans' And Military Affairs Committee"},
 'HTPWC': {'chair': 'HRUBI',
           'code': 'HTPWC',
           'meetings': [{'bills': ['SB174'],
                         'datetime': datetime.datetime(2022, 2, 15, 9, 0),
                         'timestr': '9:00 AM, room: 305, <a '
                                    "href='https://us02web.zoom.us/j/84841772756' "
                                    "target='_blank'>zoom link</a>, <a "
                                    "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                    "target='_blank'>PDF schedule</a>"}],
           'members': ['HRUBI',
                       'HGAHA',
                       'HCROW',
                       'HDELA',
                       'HGARR',
                       'HHARP',
                       'HLUND',
                       'HMADR',
                       'HPETT',
                       'HPOWD',
                       'HROMA'],
           'name': 'House Transportation, Public Works & Capital Improvements'},
 'HTRC': {'chair': 'HCHAN',
          'code': 'HTRC',
          'meetings': [{'bills': ['HB125',
                                  'HB148',
                                  'HB153',
                                  'HB183',
                                  'HB194',
                                  'HB213',
                                  'SB134'],
                        'datetime': datetime.datetime(2022, 2, 12, 12, 30),
                        'timestr': '12:30 PM, room: 317, <a '
                                   "href='https://us02web.zoom.us/j/83787833093' "
                                   "target='_blank'>zoom link</a>, <a "
                                   "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                   "target='_blank'>PDF schedule</a>"},
                       {'bills': ['HB125',
                                  'HB148',
                                  'HB153',
                                  'HB183',
                                  'HB194',
                                  'HB213',
                                  'SB134'],
                        'datetime': datetime.datetime(2022, 2, 12, 12, 30),
                        'timestr': '12:30 PM, room: 317, <a '
                                   "href='https://us02web.zoom.us/j/83787833093' "
                                   "target='_blank'>zoom link</a>, <a "
                                   "href='https://nmlegis.gov/Agendas/Standing/hSched021222.pdf' "
                                   "target='_blank'>PDF schedule</a>"}],
          'members': ['HCHAN',
                      'HHEPA',
                      'HCADA',
                      'HEGOL',
                      'HHARP',
                      'HHERN',
                      'HLENT',
                      'HLUTA',
                      'HMARJ',
                      'HMONR',
                      'HROAN',
                      'HSCOT',
                      'HSTRI'],
          'name': 'House Taxation & Revenue'},
 'SFC': {'chair': 'SMUNO',
         'code': 'SFC',
         'meetings': [{'bills': ['HB2',
                                 'HB8',
                                 'SB155',
                                 'SB202',
                                 'SB243',
                                 'SB69'],
                       'datetime': datetime.datetime(2022, 2, 12, 10, 0),
                       'timestr': '10:00 AM or Call of Chair, room: 322, <a '
                                  "href='https://us02web.zoom.us/j/81679647964' "
                                  "target='_blank'>zoom link</a>, <a "
                                  "href='https://nmlegis.gov/Agendas/Standing/sSched021222.pdf' "
                                  "target='_blank'>PDF schedule</a>"},
                      {'bills': ['HB2',
                                 'HB8',
                                 'SB155',
                                 'SB202',
                                 'SB243',
                                 'SB69'],
                       'datetime': datetime.datetime(2022, 2, 12, 10, 0),
                       'timestr': '10:00 AM or Call of Chair, room: 322, <a '
                                  "href='https://us02web.zoom.us/j/81679647964' "
                                  "target='_blank'>zoom link</a>, <a "
                                  "href='https://nmlegis.gov/Agendas/Standing/sSched021222.pdf' "
                                  "target='_blank'>PDF schedule</a>"}],
         'members': ['SMUNO',
                     'SRODR',
                     'SSHAR',
                     'SBURT',
                     'SCAMP',
                     'SDIAM',
                     'SGONZ',
                     'SHEMP',
                     'SPADI',
                     'SSTEI',
                     'SWOOD'],
         'name': 'Senate Finance'},
 'SHPAC': {'chair': 'SORTI',
           'code': 'SHPAC',
           'meetings': [{'bills': ['HB22', 'HB56', 'HB81'],
                         'datetime': datetime.datetime(2022, 2, 11, 13, 30),
                         'timestr': '1:30 PM or 1/2 hr after session, room: '
                                    '311, <a '
                                    "href='https://us02web.zoom.us/j/87967039414' "
                                    "target='_blank'>zoom link</a>, <a "
                                    "href='https://nmlegis.gov/Agendas/Standing/sSched021122.pdf' "
                                    "target='_blank'>PDF schedule</a>"}],
           'members': ['SORTI',
                       'STALL',
                       'SSCHM',
                       'SGADM',
                       'SINGL',
                       'SMCKE',
                       'SSEDI',
                       'SSTEF'],
           'name': 'Senate Health & Public Affairs'},
 'SIRC': {'chair': 'SPINS',
          'code': 'SIRC',
          'meetings': [{'bills': ['HB15'],
                        'datetime': datetime.datetime(2022, 2, 11, 13, 30),
                        'timestr': '1:30 PM or 1/2 hr after, room: 303, <a '
                                   "href='https://us02web.zoom.us/j/84137686373' "
                                   "target='_blank'>zoom link</a>, <a "
                                   "href='https://nmlegis.gov/Agendas/Standing/sSched021122.pdf' "
                                   "target='_blank'>PDF schedule</a>"}],
          'members': ['SPINS', 'SJARA', 'SGRIG', 'SMCKE', 'SSANJ', 'SSHEN'],
          'name': 'Senate Indian, Rural & Cultural Affairs'},
 'SJC': {'chair': 'SCERV',
         'code': 'SJC',
         'meetings': [{'bills': ['HB135',
                                 'HB52',
                                 'HB55',
                                 'SB100',
                                 'SB150',
                                 'SB152',
                                 'SB178',
                                 'SB42',
                                 'SB54',
                                 'SJR7'],
                       'datetime': datetime.datetime(2022, 2, 12, 10, 0),
                       'timestr': '10:00 AM, room: 311, <a '
                                  "href='https://us02web.zoom.us/j/83347538157' "
                                  "target='_blank'>zoom link</a>, <a "
                                  "href='https://nmlegis.gov/Agendas/Standing/sSched021222.pdf' "
                                  "target='_blank'>PDF schedule</a>"},
                      {'bills': ['HB135',
                                 'HB52',
                                 'HB55',
                                 'SB100',
                                 'SB150',
                                 'SB152',
                                 'SB178',
                                 'SB42',
                                 'SB54',
                                 'SJR7'],
                       'datetime': datetime.datetime(2022, 2, 12, 10, 0),
                       'timestr': '10:00 AM, room: 311, <a '
                                  "href='https://us02web.zoom.us/j/83347538157' "
                                  "target='_blank'>zoom link</a>, <a "
                                  "href='https://nmlegis.gov/Agendas/Standing/sSched021222.pdf' "
                                  "target='_blank'>PDF schedule</a>"}],
         'members': ['SCERV',
                     'SDUHI',
                     'SPIRT',
                     'SBACA',
                     'SIVEY',
                     'SLOPE',
                     'SMOOR',
                     'SONEI',
                     'SSTEW'],
         'name': 'Senate Judiciary'},
 'SRC': {'code': 'SRC',
         'meetings': [],
         'members': ['SJARA',
                     'SINGL',
                     'SBACA',
                     'SDUHI',
                     'SIVEY',
                     'SLOPE',
                     'SMOOR',
                     'SORTI',
                     'SPIRT',
                     'SSTEW',
                     'SWIRT'],
         'name': 'Senate Rules'},
 'STBTC': {'chair': 'SSHEN',
           'code': 'STBTC',
           'meetings': [{'bills': ['HB47', 'HB71', 'HB82', 'HB95', 'SB198'],
                         'datetime': datetime.datetime(2022, 2, 12, 9, 0),
                         'timestr': '9:00 AM, room: 321, <a '
                                    "href='https://us02web.zoom.us/j/84895112616' "
                                    "target='_blank'>zoom link</a>, <a "
                                    "href='https://nmlegis.gov/Agendas/Standing/sSched021222.pdf' "
                                    "target='_blank'>PDF schedule</a>"}],
           'members': ['SSHEN',
                       'SHAMB',
                       'SKERN',
                       'SBRAN',
                       'SGRIG',
                       'SHICK',
                       'SJARA',
                       'SSANJ',
                       'STALL',
                       'SWIRT'],
           'name': 'Senate Tax, Business & Transportation'}
    }

# def test_get_legislators():
#     nmlegisbill.get_legislator_list_from_XLS()
#     print("Fetched legislator list")

#
# Clean up after other tests in this file are finished
#
def pytest_runtest_teardown():
    print("Cleaning up")
    try:
        jsonbackup = "tests/cache/allbills_%s.json" \
            % (datetime.datetime.now()
               - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        if os.path.exists(jsonbackup):
            # os.system("ls -l " + jsonbackup)
            os.unlink(jsonbackup)
    except Exception as e:
        print("Couldn't unlink", jsonbackup, ":", e)
