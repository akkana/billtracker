
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from config import Config

import os

app = Flask(__name__)

app.config.from_object(Config)

# Some global variables that need to be importable, but shouldn't
# be set up unless we're consciously setting up a flask app
# (e.g. the tests for nmlegis parsing shouldn't set them up).
db = None
migrate = None
login = None
mail = None

def initialize_flask_session():
    global db, migrate, login, mail, SQLALCHEMY_DATABASE_URI

    print(">>>>>>>>>>>>> initializing db etc. <<<<<<<<<<<<<<<<")

    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
    db = SQLAlchemy(app)

    migrate = Migrate(app, db)

    # Not clear if this works to enable batch, but what does work is to edit
    # migrate/env.py after the first db init, and add render_as_batch=True.
    # migrate.init_app(app, db, render_as_batch=True)

    login = LoginManager(app)
    login.login_view = 'login'

    mail = Mail(app)


# This shouldn't be called here; it should be possible to import
# things from this module without actually setting up a database
# and initializing a flask session.
# initialize_flask_session()


# Uncommenting the next line leads to a null database:
# from app import routes, models
'''
 File "/home/akkana/src/billtracker/run_billtracker.py", line 12, in <module>
    from app import app
  File "/home/akkana/src/billtracker/app/__init__.py", line 43, in <module>
    from app import routes, models
  File "/home/akkana/src/billtracker/app/routes.py", line 9, in <module>
    from app.forms import LoginForm, RegistrationForm, AddBillsForm, \
  File "/home/akkana/src/billtracker/app/forms.py", line 14, in <module>
    from app.models import User
  File "/home/akkana/src/billtracker/app/models.py", line 24, in <module>
    userbills = db.Table('userbills',
                ^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'Table'
'''





'''
from flask import Flask, session
# from flask.ext.session import Session
from flask_sqlalchemy import SQLAlchemy
from config import Config


import os

app = Flask(__name__)
app.config.from_object(Config)

session_type = 'sqlalchemy'
app.config.from_object(__name__)

# The Flask session quickstart says to use this line,
# but doesn't explain what module is supposed to define Session.
# Fortunately it doesn't seem to be necessary.
# Session(app)

# from app import routes, models, api, mailapi

SQLALCHEMY_DATABASE_URI = None

'''
