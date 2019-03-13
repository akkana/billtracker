#!/usr/bin/env python3

import sys, os
sys.path.insert(1, os.path.join(sys.path[0], '..'))

import unittest

from billtracker import billtracker, db
from billtracker.models import User, Bill
from config import Config, basedir


TEST_DB = 'test.db'


class UserModelCase(unittest.TestCase):
    # setUp() will be called for every test_*() function in the class.
    def setUp(self):
        billtracker.config['TESTING'] = True
        billtracker.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + \
            os.path.join(basedir, TEST_DB)

        self.app = billtracker.test_client()

        db.drop_all()
        db.create_all()


    def tearDown(self):
        db.session.remove()
        db.drop_all()


    def test_password_hashing(self):
        print("Testing password hashing ...")
        u = User(username='testuser')
        u.set_password('testpassword')
        self.assertFalse(u.check_password('notthepassword'))
        self.assertTrue(u.check_password('testpassword'))


    def test_bills(self):
        print("Testing top-level page ...")
        response = self.app.get('/', follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        print("Testing adding a bill ...")
        response = self.app.post("/api/refresh_one_bill",
                                 data={ 'BILLNO': 'HB73',
                                        'KEY': os.getenv('SECRET_KEY') } )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'OK Updated HB73')

        print("Testing bills_by_update_date ...")
        response = self.app.get("/api/bills_by_update_date")
        self.assertEqual(response.get_data(as_text=True), 'HB73')

        print("Testing whether there is one bill in the database ...")
        allbills = Bill.query.all()
        self.assertEqual(len(allbills), 1)

        print("Testing whether the bill is in the database ...")
        bill = Bill.query.filter_by(billno="HB73").first()
        self.assertEqual(bill.billno, "HB73")
        self.assertEqual(bill.title, 'EXEMPT NM FROM DAYLIGHT SAVINGS TIME')


if __name__ == '__main__':
    unittest.main(verbosity=2)
