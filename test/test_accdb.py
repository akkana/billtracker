#!/usr/bin/env python3

import unittest
import os
from shutil import copyfile

# The database location must be set before importing the billtracker config
topdir = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
CACHEDIR = 'test/cache'
TEST_DB = '%s/test.db' % CACHEDIR
dbpath = os.path.join(topdir, TEST_DB)
DATABASE_URL = "sqlite:///%s" % dbpath

# Override environment variables used to run the app while testing,
# to ensure the test environment is independent.
# Must be done before importing flask or billtracker files.
if "DATABASE_URL" in os.environ:
    del(os.environ["DATABASE_URL"])
os.environ["DATABASE_URL"] = DATABASE_URL
if "FLASK_APP" in os.environ:
    del(os.environ["FLASK_APP"])


# Now it's safe (I hope) to import the flask stuff
from flask import Flask, session
from app import app, db, initialize_flask_session

# Even though we just imported app and db, they won't match the
# globals of that name from __init.py__ once it initializes them,
# so the initialize function must return them:
app, db = initialize_flask_session()

# Now it should be safe to import other flask objects
from app.models import Bill
from app.bills import billrequests, accdb

from config import Config, basedir

KEY = 'TESTING_NOT_SO_SECRET_KEY'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + dbpath
app.config['TESTING'] = True
app.config['SECRET_KEY'] = KEY

from app import routes, models, api, mailapi

class TestAccdb(unittest.TestCase):
    # Called for each test_* function.
    def setUp(self):
        # To see large diffs, set this:
        # self.maxDiff = None

        # Don't go to the actual nmlegis site, use cached files
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
            print("db is", db)
            db.create_all()
            print("after create_all, db is", db)
            print("Table?", db.Table)
            self.client = self.app.test_client()
            print("SQLALCHEMY_DATABASE_URI:",
                  app.config['SQLALCHEMY_DATABASE_URI'])

        # Copy to test/cache/LegInfo.accdb
        copyfile("test/files/LegInfo-24-01-24T14.accdb",
                 "test/cache/LegInfo.accdb")
        print("Copied to test/cache/LegInfo.accdb")

    # Called for each test_* function.
    def tearDown(self):
        with self.app.app_context():
            db.drop_all()

        try:
            os.unlink("test/cache/LegInfo.accdb")
        except:
            pass
        try:
            os.unlink("test/cache/LegInfo.accdb.bak")
        except:
            pass

    def setUpClass():
        # db.init_app can only be called once, so app needs to be a class var.
        __class__.app = app

        # Flask being incredibly unfriendly to unittest:
        # In 2022, db.init_app needed to be run in setUp(self).
        # In January 2023, it needed to be run here.
        # In February 2023, it causes:
        # RuntimeError: A 'SQLAlchemy' instance has already been registered on this Flask app. Import and use that instance instead.
        # with __class__.app.app_context():
        #     db.init_app(__class__.app)

    def test_accdb_bills(self):
        # Seems to be required for accessing db
        with app.test_request_context():
            # See long comment in test_billtracker.py
            with self.client.session_transaction() as session:
                session["yearcode"] = '24'

                # # Fetch the list of legislative sessions.
                # # Do this first, many things depend on current_leg_session()
                # response = self.client.post("/api/refresh_session_list",
                #                             data={ 'KEY': KEY })
                # self.assertTrue(
                #     response.get_data(as_text=True).startswith('OK'))

            # Add a couple of empty bills
            hjr7 = Bill()
            hjr7.billno = 'HJR7'
            sb43 = Bill()
            sb43.billno = 'SB43'

            accdb.update_bills([hjr7, sb43])

            db.session.add(hjr7)
            db.session.add(sb43)
            db.session.commit()

            allbills = Bill.query.all()
            self.assertEqual(len(allbills), 2)

            hjr7 = Bill.query.filter_by(billno="HJR7").first()
            print(hjr7)
            self.assertEqual(hjr7.billno, "HJR7")
            self.assertEqual(hjr7.title,
                             "COMMISSION ON LEGISLATIVE SALARIES, CA")
            # self.assertEqual(hjr7.statustext,
            #                  "Legislative Day: 2, Calendar Day: 01/22/2024, "
            #                  "Sent to HGEIC - Referrals: HGEIC/HJC")

