import os
basedir = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY') or 's945v7490wcn4w47w8n9cp'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

# administrator list
ADMINS = ['akkana@shallowsky.com']

# Email server. This will fail except on a machine that's running
# a mail server that allows local connections.
MAIL_SERVER = 'localhost'
MAIL_PORT = 25
# MAIL_PORT = 465
MAIL_USE_TLS = False
MAIL_USE_SSL = False

# MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_USERNAME = "nmbilltracker"

# MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
