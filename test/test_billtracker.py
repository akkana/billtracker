#!/usr/bin/env python3

import sys, os
sys.path.insert(1, os.path.join(sys.path[0], '..'))

import unittest

from billtracker import billtracker, db
from billtracker.models import User
from config import Config


class UserModelCase(unittest.TestCase):
    def setUp(self):
        billtracker.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        billtracker.config['TESTING'] = True
        db.create_all()


    def tearDown(self):
        db.session.remove()
        db.drop_all()


    def test_password_hashing(self):
        u = User(username='testuser')
        u.set_password('testpassword')
        self.assertFalse(u.check_password('notthepassword'))
        self.assertTrue(u.check_password('testpassword'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
