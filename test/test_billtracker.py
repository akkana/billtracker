#!/usr/bin/env python3

#
# NOTE: The tests use sqlite as the database,
# which may not be what the production app uses.
#

import sys, os
# Allow importing from billtracker, one directory up from the test dir.
sys.path.insert(1, os.path.join(sys.path[0], '..'))

import unittest
import re
import json


# Some of these tests run flask routes and compare the generated HTML
# against a saved file. That means that whenever anything about the
# page changes, it breaks the tests. If you're sure that the only things
# you changed are chrome and not content, set renew_files to True and
# run the test again. It will generate the files you need to copy into
# the test/files directory to make the tests work.
# Don't forget to set it back to False afterward.
renew_files = True


# The database location must be set before importing the billtracker config
topdir = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
CACHEDIR = 'test/cache'
TEST_DB = '%s/test.db' % CACHEDIR
dbpath = os.path.join(topdir, TEST_DB)
DATABASE_URL = "sqlite:///%s" % dbpath

# Override environment variables used to run the app while testing,
# to ensure the test environment is independent.
os.environ["DATABASE_URL"] = DATABASE_URL
if "FLASK_APP" in os.environ:
    del(os.environ["FLASK_APP"])
if "MAIL_SERVER" in os.environ:
    del(os.environ["MAIL_SERVER"])
if "MAIL_USERNAME" in os.environ:
    del(os.environ["MAIL_USERNAME"])
if "MAIL_PASSWORD" in os.environ:
    del(os.environ["MAIL_PASSWORD"])
os.environ["MAIL_SUPPRESS_SEND"] = "True"

# Now it's safe (I hope) to import the flask stuff
from flask import Flask, session
from billtracker import billtracker, db
from billtracker.models import User, Bill, LegSession
from billtracker.bills import billrequests

from config import Config, basedir

KEY = 'TESTING_NOT_SO_SECRET_KEY'
billtracker.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + dbpath
billtracker.config['TESTING'] = True
billtracker.config['SECRET_KEY'] = KEY

# To help with submitting form data from tests
# -- but form.validate_on_submit still returns False.
billtracker.config['WTF_CSRF_ENABLED'] = False

# Needed for captcha validation
from billtracker.forms import RegistrationForm
from billtracker.routes import initialize_captcha
from billtracker import chattycaptcha


class TestBillTracker(unittest.TestCase):
    # Called for each test_* function.
    def setUp(self):
        # To see large diffs, set this:
        # self.maxDiff = None

        # Don't go to the actual nmlegis site
        billrequests.LOCAL_MODE = True
        billrequests.CACHEDIR = CACHEDIR

        try:
            os.unlink(dbpath)
            print("Removed", dbpath)
        except FileNotFoundError:
            print("No", dbpath, "to remove")

        # Uncomment to get verbose information on cache/net requests:
        # billrequests.DEBUG = True

        self.app = __class__.app
        with self.app.app_context():
            db.create_all()
            self.client = self.app.test_client()
            print("SQLALCHEMY_DATABASE_URI:",
                  billtracker.config['SQLALCHEMY_DATABASE_URI'])

    # Called for each test_* function.
    def tearDown(self):
        with self.app.app_context():
            db.drop_all()

    def setUpClass():
        # db.init_app can only be called once, so app needs to be a class var.
        __class__.app = billtracker

        # Flask being incredibly unfriendly to unittest:
        # In 2022, db.init_app needed to be run in setUp(self).
        # In January 2023, it needed to be run here.
        # In February 2023, it causes:
        # RuntimeError: A 'SQLAlchemy' instance has already been registered on this Flask app. Import and use that instance instead.
        # with __class__.app.app_context():
        #     db.init_app(__class__.app)

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

        # Seems to be required for accessing db
        with billtracker.test_request_context():

            # Empirically, the way flask 2.2 works is that
            # "with self.client.session_transaction()"
            # lets you create the session object, but it won't
            # be visible in other places, like routes and forms,
            # until you exit the "with" clause, at which point it
            # magically becomes the global flask.session.
            # (But sometimes it's globally accessible even inside the with.)
            # Anything added to it later in this file, outside
            # the "with", will only add to a local copy and won't
            # be copied into the outside-visible session.
            with self.client.session_transaction() as session:
                session["yearcode"] = '19'

                # Fetch the list of legislative sessions.
                # Do this first, many things depend on current_leg_session()
                response = self.client.post("/api/refresh_session_list",
                                            data={ 'KEY': KEY })
                self.assertTrue(response.get_data(as_text=True).startswith('OK'))

                # Set up form and session variables that will be
                # used later to create a user.
                # These apparently have to be created inside
                # the original 'with' clause.
                USERNAME = "testuser"
                PASSWORD = "testpassword"
                form = RegistrationForm()
                form.username.data = USERNAME
                form.password.data = PASSWORD
                form.password2.data = PASSWORD

                initialize_captcha()
                session["capq"] = next(iter(chattycaptcha.captcha.QandA))
                capa = chattycaptcha.captcha.QandA[session["capq"]][0]

            # Now exited the "with", so session should now be visible
            # from anywhere.

            # Fetch the list of legislative sessions.
            # Do this first, many things depend on current_leg_session()
            response = self.client.post("/api/refresh_session_list",
                                     data={ 'KEY': KEY })
            self.assertTrue(response.get_data(as_text=True).startswith('OK'))
            leg_sessions = LegSession.query.all()

            # Check that the home page loads.
            # This has nothing to do with bills, but calling setUp/tearDown
            # just for this would be a waste of cycles.
            # This will redirect to the login page, login().
            response = self.client.get('/index', follow_redirects=True)
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)

            # Add a new bill, using the already cached page
            response = self.client.post("/api/refresh_one_bill",
                                     data={ 'BILLNO': 'HB73', 'KEY': KEY,
                                            'YEARCODE': '19'} )
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)
            self.assertEqual(response.get_data(as_text=True), 'OK Updated HB73')

            # There should be exactly one bill in the database now
            allbills = Bill.query.all()
            self.assertEqual(len(allbills), 1)

            # Test that bills_by_update_date now shows the bill
            response = self.client.post("/api/bills_by_update_date",
                                    data={ 'yearcode': '19' })
            self.assertEqual(response.get_data(as_text=True), 'HB73')

            # Same thing but with GET
            response = self.client.get("/api/bills_by_update_date?yearcode=19")
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

            # Needed to test WTForms to test any POSTs:
            billtracker.config['WTF_CSRF_ENABLED'] = False

            response = self.client.post("/newaccount",
                                     data={ 'username': USERNAME,
                                            'password': PASSWORD,
                                            'password2': PASSWORD,
                                            'capq': session["capq"],
                                            'capa' : capa,
                                            'submit': 'Register' })
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)
            allusers = User.query.all()
            self.assertEqual(len(allusers), 1)
            user = User.query.filter_by(username='testuser').first()
            self.assertEqual(user.username, 'testuser')

            # Try addbills without being logged in:
            response = self.client.post('/addbills',
                                     data={ 'billno':   'HB73',
                                            'yearcode': '19',
                                            'submit':   'Track a Bill'})
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)
            self.assertEqual(response.headers['location'],
                             # 2022 change: this used to be the location:
                             # 'http://localhost/login')
                             # but now it's:
                             '/login')

            # Now log in
            response = self.client.post('/login', data=dict(
                username=USERNAME,
                password=PASSWORD
            ), follow_redirects=True)
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)
            text_response = response.get_data(as_text=True)
            self.assertTrue("Bills testuser is tracking:"
                            in text_response)
            self.assertTrue("This is your first check"
                            in text_response)
            # No email specified, so that warning shouldn't be there
            self.assertTrue("Warning: Your email hasn't been confirmed yet"
                            not in text_response)

            # view the index with yearcode 19, to set the yearcode in the session.
            response = self.client.get("/?yearcode=19")
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)

            # Now try addbills again as a logged-in user:
            response = self.client.post('/addbills',
                                     data={ 'billno': 'HB73',
                                            'yearcode': '19',
                                            'submit': 'Track a Bill' })
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)

            response = self.client.post('/addbills',
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
            response = self.client.get('/', follow_redirects=True)
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
            response = self.client.post('/addbills',
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

            response = self.client.post('/addbills',
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

            response = self.client.post('/addbills',
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
            response = self.client.post('/addbills',
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
            response = self.client.get("/allbills?yearcode=19")
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)

            response_html = response.get_data(as_text=True)

            with open("test/files/allnewbills.html") as fp:
                expected_html = fp.read()
            if renew_files:
                if response_html != expected_html:
                    with open("/tmp/allnewbills.html", "w") as outfp:
                        outfp.write(response_html)
                    print("************ allnewbills will fail without: "
                        "cp /tmp/allnewbills.html test/files/allnewbills.html")
            else:
                with open("/tmp/response.html", 'w') as ofp:
                    ofp.write(response_html)
                self.assertEqual(response_html, expected_html)

            # Now all the bills have been seen, none should be new.
            response = self.client.get("/allbills?yearcode=19")
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)
            response_html = response.get_data(as_text=True)

            with open("test/files/nonewbills.html") as fp:
                expected_html = fp.read()
            if renew_files:
                if response_html != expected_html:
                    with open("/tmp/nonewbills.html", "w") as outfp:
                        outfp.write(response_html)
                    print("************ nonewbills will fail without: "
                          "cp /tmp/nonewbills.html test/files/nonewbills.html")
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
            response = self.client.post("/api/refresh_one_bill",
                                     data={ 'BILLNO': 'HB73', 'KEY': KEY,
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
            response = self.client.get("/allbills?yearcode=19")
            self.assertTrue(response.status_code == 200 or
                            response.status_code == 302)
            response_html = response.get_data(as_text=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
