import os
basedir = os.path.abspath(os.path.dirname(__file__))


def str2bool(s):
    if not s: return False
    if s[0].upper() != 'T': return False
    s = s.lower()
    return s == 't' or s == 'true'


class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY') or 's945v7490wcn4w47w8n9cp'

    # Default to using a sqlite database named "billtracker.db".
    # Note: if you use autocompletion, that may become annoying
    # and you might want to rename it.
    # To use something else, change it in the run script, e.g.
    # os.environ["SQLALCHEMY_DATABASE_URI"] = "postgresql:///dbname"
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

    # Store the "next" link in the session, not as a GET parameter.
    # without this, going to / redirects to /login?next=%2F
    # and there doesn't seem to be any way to get rid of the %2F
    # redirect or pass it as POST rather than GET.
    USE_SESSION_FOR_NEXT = True

    # A short status message highlighted at the top of every page.
    # For instance, it might say "The current session ends on 2/21".
    BILLTRACKER_INFO = os.environ.get('BILLTRACKER_INFO') or None
    BILLTRACKER_ALERT = os.environ.get('BILLTRACKER_ALERT') or None


# administrator list
ADMINS = [ os.environ.get('FLASK_ADMIN') or 'user@example.com']

