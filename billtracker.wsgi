#!/usr/bin/env python3

import sys, os

sys.path.insert(0, '/var/www/nmbilltracker/billtracker')

# And the venv for anything installed via pip:
sys.path.insert(0, '/path/to/venv/lib/python3.XX/site-packages/')

os.environ["FLASK_ADMIN"] = 'ADMIN_EMAIL'

# To enable postgres:
os.environ["DATABASE_URL"] = 'YOUR_DATABASE_URL'

# Put any special messages here, e.g. when a session is in progress,
# when will it end? Can be either .environ["BILLTRACKER_INFO"] = ""
# or os.environ["BILLTRACKER_ALERT"] = ""

from app import app as application

from app import initialize_flask_session

initialize_flask_session()

# Set up your secret key, used for things like API calls
application.secret_key = 'YOUR SECRET KEY'
