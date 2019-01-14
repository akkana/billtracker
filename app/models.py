from datetime import datetime
from app import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


# Many-to-many relationship between users and bills requires
# (or at least recommends) a relationship table,
# even if we're only querying one way and only want to list the
# bills for each user, not the users for each bill.
# http://flask-sqlalchemy.pocoo.org/2.3/models/
userbills = db.Table('userbills',
                     db.Column('user_id', db.Integer,
                               db.ForeignKey('user.id'), primary_key=True),
                     db.Column('bill_id', db.Integer,
                               db.ForeignKey('bill.id'), primary_key=True))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))

    # For authenticating users by email on password changes, etc.
    auth_code = db.Column(db.String(20), nullable=True)

    # List of bills the user cares about (many to many)
    bills = db.relationship('Bill', secondary=userbills, lazy='subquery',
                            backref=db.backref('users', lazy=True))

    last_check = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return '<User %s (%d)>' % (self.username, self.id)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # temp
    def show_bills(self):
        return "You have %d bills:<br>%s" % (len(self.bills), self.bills)


@login.user_loader
def load_user(id):
    return User.query.get(int(id))


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Bill designation, e.g. SB172
    billno = db.Column(db.String(20))

    # When did this bill's status last change on NMLegis?
    mod_date = db.Column(db.DateTime)

    # When did we last check the bill's page?
    update_date = db.Column(db.DateTime)

    # Date of last action as represented in the status on NMLegis.gov
    last_action_date = db.Column(db.DateTime)

    # Chamber (S or H)
    chamber = db.Column(db.String(2))

    # Bill type, e.g. B (bill), M (memorial), JR (joint resolution)
    billtype = db.Column(db.String(10))

    # Number, e.g. 83 for SB83
    number = db.Column(db.String(10))

    # Year (default to current)
    year = db.Column(db.String(4))

    # Bill title", "URL to HTML text of bill
    title = db.Column(db.String(200))

    # Status (last action) on the bill, in HTML format
    statusHTML = db.Column(db.String(500))

    # Status (last action) on the bill, in plaintext format
    statustext = db.Column(db.String(500))

    # Bill's sponsor (legislator who introduced it)
    sponsor = db.Column(db.String(20))

    # URL for bill's sponsor
    sponsorlink = db.Column(db.String(150))

    # Current location (e.g. which committee
    curloc = db.Column(db.String(20))

    # Link for current location
    curloclink = db.Column(db.String(150))

    # Link to FIR analysis, if any
    FIRlink = db.Column(db.String(150))

    # Link to LESC analysis, if any
    LESClink = db.Column(db.String(150))

    # Link to amendments PDF, if any
    amendlink = db.Column(db.String(150))

    # We'll seldom need to know uses for a bill, so no need to
    # include it as a line here.
    # user = db.relationship('User', secondary=userbills, lazy='subquery',
    #                         backref=db.backref('bills', lazy=True))

    def __repr__(self):
        return 'Bill %s' % (self.billno)

    def show_html(self):
        s = '<b>%s</b>:' % self.billno
        if self.mod_date:
            s += 'Modified %s' % str(self.mod_date)
        if self.statusHTML:
            s += '<br>' + self.statusHTML
        return s

