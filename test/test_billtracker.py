#!/usr/bin/env python3

#
# NOTE: The tests use sqlite as the database,
# which may not be what the production app uses.
#

import sys, os
sys.path.insert(1, os.path.join(sys.path[0], '..'))

import unittest
from unittest import mock
import re

from billtracker import billtracker, db
from billtracker.models import User, Bill
from config import Config, basedir


TEST_DB = 'test.db'

# This method will be used by the mock to replace requests.get
def mocked_requests_get(*args, **kwargs):
    class MockResponse:
        def __init__(self, text, status_code):
            self.text = text
            self.status_code = status_code

    print("******** mocked response, args =", args)
    realurl = args[0]
    m = re.match('https?://www.nmlegis.gov/Legislation/Legislation\?chamber=(.)&legtype=(.)&legno=(\d+)&year=(\d\d)', realurl)
    if m:
        chamber, legtype, billno, year = m.groups()
        filename = 'test/cache/20%s-%s%s%s.html' % (year, chamber,
                                                    legtype, billno)
        if os.path.exists(filename):
            with open(filename) as fp:
                print("filename", filename)
                return MockResponse(fp.read(), 200)
        print("Cache filename", filename, "doesn't exist")
    else:
        print("URL '%s' didn't match pattern" % realurl)

    return MockResponse(None, 404)


class TestBillTracker(unittest.TestCase):
    # setUp() will be called for every test_*() function in the class.
    def setUp(self):
        self.key = 'TESTING_NOT_SO_SECRET_KEY'

        billtracker.config['TESTING'] = True
        billtracker.config['SECRET_KEY'] = self.key

        self.dbname = os.path.join(basedir, TEST_DB)
        billtracker.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + self.dbname

        self.app = billtracker.test_client()

        db.drop_all()
        db.create_all()


    def tearDown(self):
        db.session.remove()
        db.drop_all()
        print("Removing", self.dbname)
        os.unlink(self.dbname)


    def test_password_hashing(self):
        print("Testing password hashing ...")
        u = User(username='testuser')
        u.set_password('testpassword')
        self.assertFalse(u.check_password('notthepassword'))
        self.assertTrue(u.check_password('testpassword'))


    @mock.patch('requests.get', side_effect=mocked_requests_get)
    def test_bills_and_users(self, mock_get):
        '''Test adding new users and bills to the database.'''
        # Users and bills depend on each other, so they pretty much
        # need to be combined in the same test.

        # Check that the home page loads.
        # This has nothing to do with bills, but calling setUp/tearDown
        # just for this would be a waste of cycles
        response = self.app.get('/', follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Add a new bill, using the already cached page
        response = self.app.post("/api/refresh_one_bill",
                                 data={ 'BILLNO': 'HB73', 'KEY': self.key,
                                        'YEAR': '2019'} )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'OK Updated HB73')

        # Test that bills_by_update_date now shows the bill
        response = self.app.get("/api/bills_by_update_date")
        self.assertEqual(response.get_data(as_text=True), 'HB73')

        # Testing whether there is exactly one bill in the database now
        allbills = Bill.query.all()
        self.assertEqual(len(allbills), 1)

        # Test whether the bill just added is in the database ...")
        bill = Bill.query.filter_by(billno="HB73").first()
        self.assertEqual(bill.billno, "HB73")
        self.assertEqual(bill.title, 'EXEMPT NM FROM DAYLIGHT SAVINGS TIME')

        # This is needed to test WTForms to test any POSTs:
        billtracker.config['WTF_CSRF_ENABLED'] = False

        # Create a user.
        # Don't set email address, or it will try to send a confirmation mail.
        response = self.app.post("/newaccount",
                                 data={ 'username': 'testuser',
                                        'password': 'password',
                                        'password2': 'password',
                                        'submit': 'Register' })
        self.assertEqual(response.status_code, 302)
        allusers = User.query.all()
        self.assertEqual(len(allusers), 1)
        user = User.query.filter_by(username='testuser').first()
        self.assertEqual(user.username, 'testuser')

        # Try addbills without being logged in:
        response = self.app.post('/addbills',
                                 data={ 'billno': 'HB73',
                                        'submit': 'Track a Bill'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'],
                         'http://localhost/login?next=%2Faddbills')

        # Now try logging in:
        with self.app as c:
            with c.session_transaction() as sess:
                sess['user_id'] = int(user.get_id())
                # http://pythonhosted.org/Flask-Login/#fresh-logins
                sess['_fresh'] = True

        # Now try addbills again as a logged-in user:
        response = self.app.post('/addbills',
                                 data={ 'billno': 'HB73',
                                        'submit': 'Track a Bill'})
        self.assertEqual(response.status_code, 200)

        # Need to re-query the user to get the updated bill list:
        user = User.query.filter_by(username='testuser').first()
        self.assertEqual(len(user.bills), 1)
        self.assertEqual(user.bills[0].billno, 'HB73')


if __name__ == '__main__':
    unittest.main(verbosity=2)
