from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)

migrate = Migrate(app, db)

# Not clear if this works to enable batch, but what does work is to edit
# migrate/env.py after the first db init, and add render_as_batch=True.
# migrate.init_app(app, db, render_as_batch=True)

login = LoginManager(app)
login.login_view = 'login'

from flask_mail import Mail
mail = Mail(app)

from app import routes, models
