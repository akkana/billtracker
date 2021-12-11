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
from billtracker.bills import billrequests
from config import Config, basedir

import json


CACHEDIR = 'test/cache'
TEST_DB = '%s/test.db' % CACHEDIR


# Some of these tests run flask routes and compare the generated HTML
# against a saved file. That means that whenever anything about the
# page changes, it breaks the tests. If you're sure that the only things
# you changed are chrome and not content, set renew_files to True and
# run the test again. It will generate the files you need to copy into
# the test/files directory to make the tests work.
# Don't forget to set it back to False afterward.
renew_files = True


class TestBillTracker(unittest.TestCase):
    # setUp() will be called for every test_*() function in the class.
    def setUp(self):
        self.key = 'TESTING_NOT_SO_SECRET_KEY'

        # Don't go to the actual nmlegis site
        billrequests.LOCAL_MODE = True
        billrequests.CACHEDIR = CACHEDIR

        # Uncomment to get verbose information on cache/net requests:
        # billrequests.DEBUG = True

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
        os.unlink(self.dbname)

    def test_password_hashing(self):
        u = User(username='testuser')
        u.set_password('testpassword')
        self.assertFalse(u.check_password('notthepassword'))
        self.assertTrue(u.check_password('testpassword'))

    def test_bills_and_users(self):
        """Test adding new users and bills to the database.
        """
        # Users and bills depend on each other, so they pretty much
        # need to be combined in the same test.

        # Check that the home page loads.
        # This has nothing to do with bills, but calling setUp/tearDown
        # just for this would be a waste of cycles.
        # This will redirect to the login page, login().
        response = self.app.get('/index', follow_redirects=True)
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)

        # Add a new bill, using the already cached page
        response = self.app.post("/api/refresh_one_bill",
                                 data={ 'BILLNO': 'HB73', 'KEY': self.key,
                                        'YEARCODE': '19'} )
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        self.assertEqual(response.get_data(as_text=True), 'OK Updated HB73')

        # There should be exactly one bill in the database now
        allbills = Bill.query.all()
        self.assertEqual(len(allbills), 1)

        # Test that bills_by_update_date now shows the bill
        response = self.app.get("/api/bills_by_update_date",
                                data={ 'yearcode': '19' })
        self.assertEqual(response.get_data(as_text=True), 'HB73')

        # Test whether the bill just added is in the database
        bill = Bill.query.filter_by(billno="HB73").first()
        self.assertEqual(bill.billno, "HB73")
        self.assertEqual(bill.title, 'EXEMPT NM FROM DAYLIGHT SAVINGS TIME')

        # Add a bill that has mostly null fields.
        bill = Bill()
        billdata = {
            'billno': 'HB100',
            'chamber': 'H',
            'billtype': 'B',
            'number': '100',
            'year': '19',
            'title': 'BILL WITH NULL STUFF',
            'sponsor': None,
            'sponsorlink': None,
            'contentslink': None,
            'amendlink': None,
            'last_action_date': None,
            'statusHTML': None,
            'statustext': None,
            'FIRlink': None,
            'LESClink': None,
            'update_date': None,
            'mod_date': None
        }
        bill.set_from_parsed_page(billdata)
        db.session.add(bill)
        db.session.commit()

        # Fetch the list of legislative sessions
        response = self.app.post("/api/refresh_session_list",
                                 data={ 'KEY': self.key })
        self.assertTrue(response.get_data(as_text=True).startswith('OK'))

        # This is needed to test WTForms to test any POSTs:
        billtracker.config['WTF_CSRF_ENABLED'] = False

        # Create a user.
        # Don't set email address, or it will try to send a confirmation mail.
        USERNAME = "testuser"
        PASSWORD = "testpassword"
        response = self.app.post("/newaccount",
                                 data={ 'username': USERNAME,
                                        'password': PASSWORD,
                                        'password2': PASSWORD,
                                        'capa' : 'yes',
                                        'submit': 'Register' })
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        allusers = User.query.all()
        self.assertEqual(len(allusers), 1)
        user = User.query.filter_by(username='testuser').first()
        self.assertEqual(user.username, 'testuser')

        # Try addbills without being logged in:
        response = self.app.post('/addbills',
                                 data={ 'billno':   'HB73',
                                        'yearcode': '19',
                                        'submit':   'Track a Bill'})
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        self.assertEqual(response.headers['location'],
                         'http://localhost/login')

        # Now log in
        response = self.app.post('/login', data=dict(
            username=USERNAME,
            password=PASSWORD
        ), follow_redirects=True)
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        text_response = response.get_data(as_text=True)
        self.assertTrue("Warning: Your email hasn't been confirmed yet"
                        in text_response)
        self.assertTrue("Bills testuser is tracking:"
                        in text_response)
        self.assertTrue("This is your first check"
                        in text_response)

        # view the index with yearcode 19, to set the yearcode in the session.
        response = self.app.get("/?yearcode=19")
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)

        # Now try addbills again as a logged-in user:
        response = self.app.post('/addbills',
                                 data={ 'billno': 'HB73',
                                        'yearcode': '19',
                                        'submit': 'Track a Bill' })
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)

        response = self.app.post('/addbills',
                                 data={ 'billno': 'HB100',
                                        'yearcode': '19',
                                        'submit': 'Track a Bill' })
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)

        # Need to re-query the user to get the updated bill list (why??):
        user = User.query.filter_by(username='testuser').first()

        self.assertEqual(len(user.bills), 2)
        self.assertEqual(user.bills[0].billno, 'HB73')
        self.assertEqual(user.bills[1].billno, 'HB100')

        # Now test the index page again
        response = self.app.get('/', follow_redirects=True)
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        pageHTML = response.get_data(as_text=True)
        self.assertTrue('HB73' in pageHTML)
        self.assertTrue('HB100' in pageHTML)

        # Make sure untracking works too
        # Failing to re-query user here sometimes results in:
        # sqlalchemy.orm.exc.DetachedInstanceError: Parent instance <User at 0x7f0393d60490> is not bound to a Session; lazy load operation of attribute 'bills' cannot proceed (Background on this error at: http://sqlalche.me/e/13/bhk3)
        user = User.query.filter_by(username='testuser').first()
        bill0, bill1 = user.bills
        user.bills.remove(bill0)
        user.bills.remove(bill1)
        db.session.add(user)
        db.session.commit()
        user = User.query.filter_by(username='testuser').first()
        self.assertEqual(len(user.bills), 0)

        #
        # Test edge case syntaxes users might type into the addbills page,
        # and also make sure incorrect billnumbers aren't added
        # to the database from parse errors
        #
        response = self.app.post('/addbills',
                                 data={ 'billno': " HB100",
                                        'yearcode': '19',
                                        'submit': 'Track a Bill' })
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        self.assertIn("""<span style="color: red;">[Bills should start with""",
                      response.get_data(as_text=True))
        user = User.query.filter_by(username="testuser").first()
        self.assertEqual(len(user.bills), 0)
        allbills = Bill.query.all()
        self.assertEqual(len(allbills), 2)

        response = self.app.post('/addbills',
                                 data={ 'billno': "HB-100",
                                        'yearcode': '19',
                                        'submit': 'Track a Bill' })
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        pageHTML = response.get_data(as_text=True)
        self.assertIn("""<div class="error">""", pageHTML)
        user = User.query.filter_by(username="testuser").first()
        self.assertEqual(len(user.bills), 0)

        allbills = Bill.query.all()
        self.assertEqual(len(allbills), 2)

        response = self.app.post('/addbills',
                                 data={ 'billno': "HB  100 ",
                                        'yearcode': '19',
                                        'submit': 'Track a Bill' })
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        user = User.query.filter_by(username="testuser").first()
        self.assertEqual(len(user.bills), 1)

        allbills = Bill.query.all()
        self.assertEqual(len(allbills), 2)

        # Remove all the user's bills, to start over
        def untrackall():
            # This function apparently doesn't inherit user
            # from the containing function.
            user = User.query.filter_by(username="testuser").first()
            userbills = user.bills
            for b in userbills:
                user.bills.remove(b)
            user = User.query.filter_by(username="testuser").first()
            self.assertEqual(len(user.bills), 0)

        untrackall()

        # For a request that includes a string with a comma,
        # like "hB73, hb  100  ", the comma will be interpreted as
        # part of JSON, so it needs to be encoded first.
        userstring = "hb0073, hb  100  , hb-45 "
        response = self.app.post('/addbills',
                                 data=json.dumps({ 'billno': userstring,
                                                   'yearcode': '19',
                                                   'submit': 'Track a Bill' }),
                                 content_type='application/json')
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        user = User.query.filter_by(username="testuser").first()

        self.assertEqual(len(user.bills), 2)
        userbillnos = [ b.billno for b in user.bills ]
        self.assertTrue('HB73' in userbillnos)
        self.assertTrue('HB100' in userbillnos)

        pageHTML = response.get_data(as_text=True)
        self.assertIn("""<div class="error">""", pageHTML)
        self.assertIn("&#39;HB-45&#39; doesn&#39;t look like a bill number",
                      pageHTML)

        # Some bills_seen tests
        billno_list = [ 'SB1', 'SB2', 'SB3' ]
        user.update_bills_seen(','.join(billno_list), '19')
        seen = user.get_bills_seen('19')
        self.assertEqual(seen, billno_list)

        user.add_to_bills_seen([ "HB1", "HB100" ], '19')
        billno_list.append("HB1")
        billno_list.append("HB100")
        seen = user.get_bills_seen('19')
        billno_list.sort()
        self.assertEqual(seen, billno_list)

        ################
        # Now check how the allbills page influences bills_seen
        user.bills_seen = ""
        db.session.add(user)
        db.session.commit()

        # allbills page: everything should be new.
        response = self.app.get("/allbills?yearcode=19")
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)

        response_html = response.get_data(as_text=True)

        with open("test/files/allnewbills.html") as fp:
            expected_html = fp.read()
        if renew_files:
            if response_html != expected_html:
                with open("/tmp/allnewbills.html", "w") as outfp:
                    outfp.write(response_html)
                print("allnewbills will fail without: "
                      "cp tmp/allnewbills.html test/files/allnewbills.html")
        else:
            self.assertEqual(response_html, expected_html)

        # Now all the bills have been seen, none should be new.
        response = self.app.get("/allbills?yearcode=19")
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        response_html = response.get_data(as_text=True)

        with open("test/files/nonewbills.html") as fp:
            expected_html = fp.read()
        if renew_files:
            if response_html != expected_html:
                with open("/tmp/nonewbills.html", "w") as outfp:
                    outfp.write(response_html)
                print("nonewbills will fail without: "
                      "cp tmp/nonewbills.html test/files/nonewbills.html")
        else:
            self.assertEqual(response_html, expected_html)

        # The next section requires a lot of substituting of
        # temporary replacement files. A pair of helpers:
        def substitute_file(filename, extra):
            os.rename(filename, filename + ".save")
            os.rename(filename + extra, filename)

        def orig_file(filename, extra):
            os.rename(filename, filename + extra)
            os.rename(filename + ".save", filename)

        # Change a bill's title. That involves moving the bill's
        # html description aside and replacing it with one that
        # has a different title.
        substitute_file("test/cache/Legislation_List_Session=57",
                        ".titlechange")
        substitute_file("test/cache/2019-HB73.html", ".titlechange")

        # Make sure the old title is the expected one
        hb73 = Bill.query.filter_by(billno="HB73").first()
        self.assertEqual(hb73.title, "EXEMPT NM FROM DAYLIGHT SAVINGS TIME")

        # Refresh HB73 so it will get the new title
        # XXX probably remove this!
        response = self.app.post("/api/refresh_one_bill",
                                 data={ 'BILLNO': 'HB73', 'KEY': self.key,
                                        'YEARCODE': '19'} )
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        self.assertEqual(response.get_data(as_text=True), 'OK Updated HB73')

        hb73 = Bill.query.filter_by(billno="HB73").first()
        self.assertEqual(hb73.title, "THIS IS A NEW TITLE FOR THIS BILL")

        # move the files back where they belong.
        orig_file("test/cache/Legislation_List_Session=57",
                  ".titlechange")
        orig_file("test/cache/2019-HB73.html", ".titlechange")

        # Now test the allbills page again to make sure it shows
        # the retitled bill as new.
        response = self.app.get("/allbills?yearcode=19")
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        response_html = response.get_data(as_text=True)


    def test_captcha(self):
        """Test adding new users with a captcha file in place
        """
        # Create a captcha file with only one question in it
        ANSWERSTR = "You betcha!"
        QUESTIONSTR = "Should this test pass?"
        questionfile = "%s/CAPTCHA-QUESTIONS" % CACHEDIR
        with open(questionfile, "w") as fp:
            print(QUESTIONSTR, file=fp)
            print(ANSWERSTR, file=fp)

        # Create a user.
        # Don't set email address, or it will try to send a confirmation mail.
        USERNAME = "testuser"
        PASSWORD = "testpassword"
        response = self.app.post("/newaccount",
                                 data={ 'username': USERNAME,
                                        'password': PASSWORD,
                                        'password2': PASSWORD,
                                        'capq' : QUESTIONSTR,
                                        'capa' : ANSWERSTR,
                                        'submit': 'Register' })
        self.assertTrue(response.status_code == 200 or
                        response.status_code == 302)
        allusers = User.query.all()
        self.assertEqual(len(allusers), 1)
        user = User.query.filter_by(username='testuser').first()
        self.assertEqual(user.username, 'testuser')


if __name__ == '__main__':
    unittest.main(verbosity=2)
