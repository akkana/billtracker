#!/usr/bin/env python3

import sys, os
sys.path.insert(1, os.path.join(sys.path[0], '..'))

import unittest

from billtracker import billtracker, db
from billtracker.models import User, Bill
from config import Config, basedir


TEST_DB = 'test.db'


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


    def test_bills(self):
        # Check that the home page loads.
        # This has nothing to do with bills, but calling setUp/tearDown
        # just for this would be a waste of cycles
        response = self.app.get('/', follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Add a new bill, using the already cached page
        response = self.app.post("/api/refresh_one_bill",
                                 data={ 'BILLNO': 'HB73', 'KEY': self.key } )
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
