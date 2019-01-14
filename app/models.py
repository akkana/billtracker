from datetime import datetime
from app import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.bills import nmlegisbill
import sys


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

    def check_for_changes(self):
        '''Have any bills changed? Update any bills that need it,
           commit the updates to the database if need be,
           and return a list of changed and unchanged bills.
        '''
        changed = []
        unchanged = []
        needs_commit = False
        for bill in self.bills:
            needs_commit |= bill.update()
            if bill.last_action_date and \
               bill.last_action_date > self.last_check:
                changed.append(bill)
            else:
                unchanged.append(bill)

        if needs_commit:
            print("Updated something, committing", file=sys.stderr)
            db.session.commit()

        return changed, unchanged

    def show_bills(self):
        '''Return a long HTML string showing bill statuses.
        '''
        changed, unchanged = self.check_for_changes()

        outstr = '<h2>Bills with recent changes:</h2>\n<table>'
        odd = True
        for bill in changed:
            if odd:
                cl = 'odd'
            else:
                cl = 'even'
            odd = not odd
            outstr += '<tr class="%s"><td>%s\n' % (cl, bill.show_html(True))
        outstr += '</table>\n'

        outstr += "<h2>Bills that haven't changed:</h2>\n<table>"
        odd = True
        for bill in unchanged:
            if odd:
                cl = 'odd'
            else:
                cl = 'even'
            odd = not odd
            outstr += '<tr class="%s"><td>%s\n' % (cl, bill.show_html(False))
        outstr += '</table>\n'

        return outstr

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

    def update(self):
        '''Have we updated this bill in the last two hours?
           Return True if we make a new update, False otherwise.
           Do not commit to the database: the caller should check
           return values and commit after all bills have been updated.
        '''
        now = datetime.now()
        if (now - self.update_date).seconds < 2*60*60:
            return False

        print("fetching billno =", self.billno, file=sys.stderr)
        b = nmlegisbill.parse_bill_page(self.billno,
                                        year=now.year,
                                        cache_locally=True)
        for k in b:
            # print("Setting", k, "to", b[k], file=sys.stderr)
            setattr(self, k, b[k])
            # print("Now self.%s is" % k, b[k], file=sys.stderr)
        self.update_date = now

        try:
            db.session.add(self)
            print("Supposedly added %s to the database" % self.billno,
                  file=sys.stderr)
        except Exception as e:
            print("Couldn't add %s to the database" % self.billno,
                  file=sys.stderr)
            print(e)
            sys.exit(1)

        return True

    def show_html(self, longform):
        '''Show a summary of the bill's status.
           longform=True is slightly longer: it assumes a bill has
           changed recently so there's a need to show what changed.
        '''
        outstr = '<b>%s</b>: %s' % (self.billno, self.title)
        if self.last_action_date:
            outstr += "<br>Last action: " + self.last_action.strftime('%m/%d/%Y')
        if self.statusHTML:
            outstr += "<br>Status: " + self.statusHTML

        return outstr

