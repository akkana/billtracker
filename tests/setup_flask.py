#!/usr/bin/env python3

"""
Boilerplate needed by any test that needs to access the
billtracker's sqlalchemy database or flask routes.
"""

import os

# Remove any reference to the database used for interactive testing;
# these tests need to start with an empty database.
# Also remove other references to the app and the email settings.
for env_var in [ "DATABASE_URL", "FLASK_APP", "SECRET_KEY",
                 "FLASK_ADMIN",
                 "MAIL_SERVER", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD",
                 "MAIL_SUPPRESS_SEND" ]:
    if env_var in os.environ:
        del(os.environ[env_var])

os.environ["CONFIG_TYPE"] = "config.TestingConfig"

topdir = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
CACHEDIR = 'tests/cache'

TEST_DB = '%s/test.db' % CACHEDIR
dbpath = os.path.join(topdir, TEST_DB)
DATABASE_URL = "sqlite:///%s" % dbpath

os.environ["DATABASE_URL"] = DATABASE_URL
os.environ["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
SQLALCHEMY_DATABASE_URI = DATABASE_URL

try:
    os.unlink(TEST_DB)
except FileNotFoundError:
    pass

# Now it's safe (I hope) to import the flask stuff
from app import app, db
from app.bills import billrequests

# Don't be accessing nmlegis or other external websites,
# or any real cache
billrequests.LOCAL_MODE = True

billrequests.CACHEDIR = CACHEDIR


