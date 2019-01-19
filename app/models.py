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

    # List of bill IDs the user has seen -- these bills may not even
    # be in the database, but they've been on the "all bills" list
    # so the user has had a chance to review them.
    # SQL doesn't have any list types, so just use comma separated.
    # Bill IDs are usually under 6 characters and a session isn't
    # likely to have more than 2500 bills, so 20000 would be a safe length.
    bills_seen = db.Column(db.String())

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
        now = datetime.now()
        oneday = 24 * 60 * 60    # seconds in a day
        changed = []
        unchanged = []
        needs_commit = False
        for bill in self.bills:
            needs_commit |= bill.update()
            # A changed bill is one that has a last_action_date since the
            # user's last_check, OR a last_action_date in the last 24 hours.
            if not self.last_check or (
                    bill.last_action_date and
                    (bill.last_action_date > self.last_check or
                     (now - bill.last_action_date).seconds < oneday)):
                changed.append(bill)
            else:
                unchanged.append(bill)

        # bill.update() might have updated something in one or more bills.
        # In that case, commit all the changes to the database together.
        if needs_commit:
            print("Updated something, committing", file=sys.stderr)
            db.session.commit()

        return changed, unchanged

    def show_bills(self, inline=False):
        '''Return a long HTML string showing bill statuses.
           If inline==True, add table row colors as inline CSS
           since email can't use stylesheets.
           Does not update last_check; the caller should.
        '''
        changed, unchanged = self.check_for_changes()

        # Make the table rows alternate color.
        # This is done through CSS on the website,
        # but through inline styles in email.
        if inline:
            rowstyles = [ 'style="background: white;"',
                          'style="background: #cfd; "' ]
            cellstyle = ' style="padding: .5em;"'
        else:
            rowstyles = [ 'class="even"',
                          'class="odd"' ]
            cellstyle = ""

        if changed:
            outstr = '''<h2>Bills with recent changes:</h2>
<table class="bill_list">
'''
            parity = 1
            for bill in changed:
                parity = 1 - parity
                outstr += '<tr %s><td%s>%s\n' % (rowstyles[parity],
                                                 cellstyle,
                                                 bill.show_html(True))
            outstr += '</table>\n'
        else:
            outstr = "<h2>No bills have changed</h2>\n"

        if unchanged:
            outstr += """<h2>Bills that haven't changed:</h2>
<table class="bill_list">
"""
            parity = 1
            for bill in unchanged:
                parity = 1 - parity
                outstr += '<tr %s><td>%s\n' % (rowstyles[parity],
                                               bill.show_html(False))
            outstr += '</table>\n'
        else:
            outstr += "<h2>No unchanged bills</h2>\n"

        return outstr

    def show_bills_text(self):
        '''Return a long plaintext string showing bill statuses.
           Does not update last_check; the caller should.
        '''
        changed, unchanged = self.check_for_changes()

        if changed:
            outstr = 'Bills with recent changes:\n\n'
            for bill in changed:
                outstr += bill.show_text(True) + "\n"
        else:
            outstr = "No bills have changed\n"

        if unchanged:
            outstr += "Bills that haven't changed:\n\n"
            for bill in unchanged:
                outstr += bill.show_html(False)
        else:
            outstr += "No unchanged bills\n"

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
        '''Have we updated this bill in the last few hours?
           Return True if we make a new update, False otherwise.
           Do not commit to the database: the caller should check
           return values and commit after all bills have been updated.
        '''
        hours = 4

        now = datetime.now()
        if (now - self.update_date).seconds < hours * 60*60:
            return False

        print("fetching billno =", self.billno, file=sys.stderr)
        b = nmlegisbill.parse_bill_page(self.billno,
                                        year=now.year,
                                        cache_locally=True)
        if b:
            for k in b:
                setattr(self, k, b[k])

            self.update_date = now
        else:
            errstr = "(Couldn't update)"
            if self.statustext:
                self.statustext = errstr + '\n' + self.statustext
            else:
                self.statustext = errstr

            if self.statusHTML:
                self.statusHTML = errstr + "<br /> " + self.statusHTML
            else:
                self.statusHTML = errstr

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
        outstr = '<b><a href="%s">%s: %s</a></b><br />' % \
            (nmlegisbill.bill_url(self.billno), self.billno, self.title)

        if self.last_action_date:
            outstr += "Last action: %s<br />" % \
                self.last_action_date.strftime('%m/%d/%Y')
        else:
            outstr += "No action yet.<br />"

        if self.statustext:
            # statusHTML is full of crap this year, so prefer statustext
            # even in HTML output until/unless I find a way around that.
            outstr += 'Status: %s<br />\n' % self.statustext
        elif self.statusHTML:
            outstr += 'Status: %s<br />\n' % self.statusHTML

        if self.curloc and self.curloclink:
            outstr += 'Current location: <a href="%s">%s</a><br />' % \
                (self.curloclink, self.curloc)
        elif self.curloc:
            outstr += 'Current location: ' + self.curloc + '<br />'

        if False and not longform:
            return outstr

        outstr += '<a href="%s">Full text of %s</a><br />' % \
            (nmlegisbill.contents_url(self.billno), self.billno)

        if self.sponsor and self.sponsorlink:
            outstr += 'Sponsor: <a href="%s">%s</a><br />' % (self.sponsorlink,
                                                              self.sponsor)

        analysis = []
        if self.amendlink:
            analysis.append('<a href="%s">Amendments</a>' % self.amendlink)

        if self.FIRlink:
            analysis.append('<a href="%s">FIR Report</a>' % self.FIRlink)

        if self.LESClink:
            analysis.append('<a href="%s">LESC Report</a>' % self.LESClink)

        if analysis:
            outstr += ' &bull; '.join(analysis)

        return outstr


    def show_text(self, longform):
        '''Show a summary of the bill's status in plaintext format.
           longform=True is slightly longer: it assumes a bill has
           changed recently so there's a need to show what changed.
        '''
        outstr = '%s: %s\n' % (self.billno, self.title)
        outstr += nmlegisbill.bill_url(self.billno) + '\n'

        if self.last_action_date:
            outstr += "Last action: %s\n" % \
                self.last_action_date.strftime('%m/%d/%Y')
        else:
            outstr += "No action yet.\n"

        if self.statustext:
            outstr += 'Status: %s\n' % self.statustext

        if self.curloc and self.curloclink:
            outstr += 'Current location: %s <%s>\n' % \
                (self.curloc, self.curloclink)
        elif self.curloc:
            outstr += 'Current location: ' + self.curloc + '\n'

        if False and not longform:
            return outstr

        outstr += 'Full text of %s: %s\n' % \
            (self.billno, nmlegisbill.contents_url(self.billno))

        if self.sponsor and self.sponsorlink:
            outstr += 'Sponsor: %s <%s>' % (self.sponsor, self.sponsorlink)

        if self.amendlink:
            outstr += 'Amendments: ' + self.amendlink + '\n'

        if self.FIRlink:
            outstr += 'FIR report: ' + self.FIRlink + '\n'

        if self.LESClink:
            outstr += 'LESC report: ' + self.LESClink + '\n'

        return outstr

