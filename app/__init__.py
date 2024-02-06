
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
    if app and db:
        return app, db

    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
    db = SQLAlchemy(app)
    print("Just initialized db ->", db)

    migrate = Migrate(app, db)
    print("after migrate, db =", db)

    # Not clear if this works to enable batch, but what does work is to edit
    # migrate/env.py after the first db init, and add render_as_batch=True.
    # migrate.init_app(app, db, render_as_batch=True)

    login = LoginManager(app)
    login.login_view = 'login'

    mail = Mail(app)

    # If this file doesn't import routes, then flask won't be
    # able to find any of its routes. But if routes are imported before
    # initialize_flask_session is called, then the database will be
    # imported too early and will be empty. So don't import
    # any other app files until the end of initialization.
    from app import routes, models, api, mailapi

    return app, db


