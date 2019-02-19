import os
basedir = os.path.abspath(os.path.dirname(__file__))


def str2bool(s):
    if not s: return False
    if s[0].upper() != 'T': return False
    s = s.lower()
    return s == 't' or s == 'true'


class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY') or 's945v7490wcn4w47w8n9cp'

    # I'm not clear on why there have to be three slashes here
    # in addition to the slash basedir starts with, but there do.
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'billtracker.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # To watch queries:
    # SQLALCHEMY_ECHO=True

    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'localhost'
    MAIL_PORT = os.environ.get('MAIL_PORT') or 25
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or "nmbilltracker"
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    MAIL_USE_TLS = str2bool(os.environ.get('MAIL_USE_TLS'))
    MAIL_USE_SSL = str2bool(os.environ.get('MAIL_USE_SSL'))

    # Needed for testing mail on a testing server:
    MAIL_SUPPRESS_SEND = str2bool(os.environ.get('MAIL_SUPPRESS_SEND'))
    MAIL_DEBUG = str2bool(os.environ.get('MAIL_DEBUG'))
    TESTING = str2bool(os.environ.get('TESTING'))

# administrator list
ADMINS = [ os.environ.get('FLASK_ADMIN') or 'user@example.com']

