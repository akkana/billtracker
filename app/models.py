from app import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.bills import nmlegisbill
from app.emails import send_email

from datetime import datetime, timedelta
import dateutil.parser
import time
import re
import random
import traceback
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


# How recent does a bill have to be to show it as "Recently changed"?
RECENT = timedelta(days=1, hours=12)

# How often should bill pages be refreshed?
BILLPAGE_REFRESH = timedelta(hours=3)

# How often should committee pages be refreshed?
COMMITTEEPAGE_REFRESH = timedelta(hours=6)


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

    # Comma-separated list of sponcodes for legislators this user
    # might want to contact:
    legislators = db.Column(db.String())

    # When did the user check in last?
    last_check = db.Column(db.DateTime, nullable=True)

    AUTH_CODE_CONFIRMED = "Confirmed"

    def __repr__(self):
        return '<User %s (%d)>' % (self.username, self.id)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def email_confirmed(self):
        return self.email and self.auth_code == self.AUTH_CODE_CONFIRMED

    def confirm_email(self):
        if not self.email:
            print("Yikes, can't confirm %s without email" % self.username)
            return
        self.auth_code = self.AUTH_CODE_CONFIRMED
        db.session.add(self)
        db.session.commit()

    def send_confirmation_mail(self):
        authcode = ''
        for i in range(5):
            charset = 'abcdefghijklmnopqrstuvwxyz0123456789'
            codelen = 6
            for i in range(codelen):
                authcode += random.choice(charset)

            if not User.query.filter_by(auth_code=authcode).first():
                break
            authcode = ''

        if not authcode:
            raise RuntimeError("Can't generate unique auth code")

        self.auth_code = authcode
        db.session.add(self)
        db.session.commit()

        send_email("New Mexico Bill Tracker Confirmation",
                   "noreply@nmbilltracker.com",
                   [ self.email ],
                   """
You either registered for a new account on the New Mexico Bill Tracker,
or changed your email address.

Username: %s
Email:    %s

Please confirm your email address so you can get daily updates about
bills that have changed by following this link:

https://nmbilltracker.com/confirm_email/%s

""" % (self.username, self.email, self.auth_code))


    def update_last_check(self):
        self.last_check = datetime.now()
        db.session.commit()
        # So this can be called from a template:
        return ''


    def bills_by_number(self):
        return sorted(self.bills, key=Bill.bill_natural_key)


    def bills_by_action_date(self):
        return sorted(self.bills_by_number(),
                      key=Bill.last_action_key)


    def show_bill_table(self, bill_list, inline=False):
        '''Return an HTML string showing status for a list of bills
           as HTML table rows.
           Does not inclue the enclosing <table> or <tbody> tags.
           If inline==True, add table row colors as inline CSS
           since email can't use stylesheets.
        '''
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

        outstr = ''
        parity = 1
        for bill in bill_list:
            parity = 1 - parity
            outstr += '<tr %s><td id="%s"%s>%s\n' % (rowstyles[parity],
                                                     bill.billno,
                                                     cellstyle,
                                                     bill.show_html())
        return outstr


@login.user_loader
def load_user(id):
    return User.query.get(int(id))


# This has to be defined before it's called from bill.update()
def get_committee(comcode):
    '''Look up the latest on a commitee and return a Committee object.
       Fetch it from the web if it doesn't exist yet or hasn't been
       updated recently, otherwise get it from the database.
       Doesn't commit the db session; the caller should do that.
    '''
    comm = Committee.query.filter_by(code=comcode).first()
    now = datetime.now()
    if comm:
        now = datetime.now()
        # How often to check committee pages
        if comm.last_check and now - comm.last_check < COMMITTEEPAGE_REFRESH:
            # It's new enough
            return comm

        # It's in the database but needs updating
    else:
        # New committee, haven't seen it before
        comm = Committee()
        comm.code = comcode

    # com is now a Committee object.
    # The only attr guaranteed to be set is code.
    comm.update()
    return comm


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

    # Number, e.g. 83 for SB83, in string form
    number = db.Column(db.String(10))

    # Year (default to current)
    year = db.Column(db.String(4))

    # Bill title
    title = db.Column(db.String(200))

    # Status (last action) on the bill, in HTML format
    statusHTML = db.Column(db.String(500))

    # Status (last action) on the bill, in plaintext format
    statustext = db.Column(db.String(500))

    # Where is the bill now? A bill can have only one location;
    # usually a committee, or "House", "Senate" etc.
    location = db.Column(db.String(10))

    # Bill's sponsor (legislator who introduced it), freetext.
    sponsor = db.Column(db.String(20))

    # URL for bill's sponsor
    sponsorlink = db.Column(db.String(150))

    # URL for the full text of the bill.
    # These are inconsistent and don't follow fixed rules based on the billno.
    contentslink = db.Column(db.String(150))

    # Link to FIR analysis, if any
    FIRlink = db.Column(db.String(150))

    # Link to LESC analysis, if any
    LESClink = db.Column(db.String(150))

    # Link to amendments PDF, if any
    amendlink = db.Column(db.String(150))

    # Is the bill scheduled to come up for debate?
    scheduled_date = db.Column(db.DateTime)

    # We'll seldom need to know uses for a bill, so no need to
    # include it as a line here.
    # user = db.relationship('User', secondary=userbills, lazy='subquery',
    #                         backref=db.backref('bills', lazy=True))

    def __repr__(self):
        return 'Bill %s' % (self.billno)

    #
    # How to sort by billno.
    # Sorting in python 3 is so unintuitive, this "key" business
    # instead of a straightforward cmp function. Oh, well.
    # See the User class for examples of how to use these keys.
    #
    @staticmethod
    def a2order(text):
        '''
        Sort in sensible order with digits considered numerically (SB33 < SB123)
        http://nedbatchelder.com/blog/200712/human_sorting.html
        '''
        if text.isdigit():
            return int(text)
        # Put Senate bills first
        if text and text[0] == 'S':
            return 'A' + text
        return text

    @staticmethod
    def natural_key(text):
        '''Natural key, digits considered as numbers, for sorting text.
        '''
        return [ Bill.a2order(c) for c in re.split('(\d+)', text) ]

    @staticmethod
    def bill_natural_key(bill):
        '''Natural key, digits considered as numbers, for sorting Bills.
        '''
        return [ Bill.a2order(c) for c in re.split('(\d+)', bill.billno) ]

    @staticmethod
    def last_action_key(bill):
        '''Sort bills by last action date, most recent first,
           with a secondary sort on billno.
           But if a bill is scheduled, put it first in the list,
           with bills that have the earliest scheduled dates first.
        '''
        # Bills scheduled for a committee meeting soon are the most
        # important and must be listed first.
        # Just checking for a scheduled date isn't enough;
        # many committees don't update their schedules regularly
        # so a bill's scheduled date may be several days in the past.
        # List those bills before bills that have no scheduled date,
        # but after bills that are actually scheduled for the future.
        if bill.scheduled_date:
            if bill.scheduled_date > datetime.now():
                # This starts with 000 so it will always come first:
                return bill.scheduled_date.strftime('0 %Y-%m-%d %H:%M:%s') \
                    + Bill.a2order(bill.billno)
            else:
                return bill.scheduled_date.strftime('1 %Y-%m-%d %H:%M:%s') \
                    + Bill.a2order(bill.billno)

        if bill.last_action_date:
            # Need to reverse the date, so later dates return an
            # earlier key. This will start with a digit other than 0.
            return '2 ' \
                + str(2000000000 -
                      time.mktime(bill.last_action_date.timetuple())) \
                + Bill.a2order(bill.billno)

        # Bills with no last_action_date come last.
        return '9 ' + Bill.a2order(bill.billno)


    def set_from_parsed_page(self, b):
        for k in b:
            # For location, a bit more is needed: look up the committee.
            if k == 'curloc':
                self.location = b['curloc']

            # Mysteriously, the converse of setattr is __getattribute__;
            # Bill has no setattr() even though the python 3.7.2 docs say
            # there should be. (Maybe that means it's an old-style class?)
            elif self.__getattribute__(k) != b[k]:
                setattr(self, k, b[k])

        self.update_date = datetime.now()


    def update(self):
        '''Have we updated this bill recently?
           If it's been too long, fetch the bill's page and update
           the database, and return True, otherwise False.
           Do not commit to the database: the caller should check
           return values and commit after all bills have been updated.
        '''

        now = datetime.now()
        if now - self.update_date < BILLPAGE_REFRESH:
            return False

        b = nmlegisbill.parse_bill_page(self.billno,
                                        year=now.year,
                                        cache_locally=True)
        if b:
            self.set_from_parsed_page(b)

        else:
            errstr = "Couldn't update %b" % self.billno
            print(errstr, file=sys.stderr)

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
        except Exception as e:
            print("Couldn't add %s to the database" % self.billno,
                  file=sys.stderr)
            print(e)

        return True


    def recent_activity(self, user=None):
        '''Has the bill changed in the last day or two, or does it
           have impending action like a scheduled committee hearing
           or the House or Senate floor?
           Or has it changed since the user's last check if that's
           longer than a day or two?
        '''
        if self.scheduled_date:
            return True
        if self.location == 'House' or self.location == 'Senate':
            return True

        if user:
            if not user.last_check:
                return True
            if not self.last_action_date:
                return False
            if self.last_action_date > user.last_check:
                return True

        if datetime.now() - self.last_action_date < RECENT:
            return True

        return False


    # Jinja templates can't import; they need methods that are part
    # of the model.
    def bill_url(self):
        return nmlegisbill.bill_url(self.billno)


    def show_html(self):
        '''Show a summary of the bill's status.
        '''
        outstr = '<b><a href="%s" target="_blank">%s: %s</a></b><br />' % \
            (self.bill_url(), self.billno, self.title)

        if self.last_action_date:
            outstr += "Last action: %s<br />" % \
                self.last_action_date.strftime('%m/%d/%Y')
        else:
            outstr += "No action yet.<br />"

        if self.location:
            l = Committee.query.filter_by(code=self.location).first()
            outstr += 'Location: <a href="%s" target="_blank">%s</a>' % \
                (l.get_link(), l.name)
            if self.scheduled_date:
                if self.scheduled_date > datetime.now():
                    outstr += ' <b>SCHEDULED: %s</b>' \
                        % self.scheduled_date.strftime('%m/%d/%Y')
                else:
                    outstr += ' Was scheduled: %s' \
                        % self.scheduled_date.strftime('%m/%d/%Y')
            elif self.location == 'House' or self.location == 'Senate':
                outstr += ' <b>%s Floor</b>' % self.location
            outstr += '<br />'
        else:
            outstr += 'Location: unknown<br />'

        if self.statustext:
            # statusHTML is full of crap this year, so prefer statustext
            # even in HTML output until/unless I find a way around that.
            outstr += 'Status: %s<br />\n' % self.statustext
        elif self.statusHTML:
            outstr += 'Status: %s<br />\n' % self.statusHTML

        contents = []
        if self.contentslink:
            contents.append('<a href="%s" target="_blank">Full text</a>' %
                            self.contentslink)
        else:
            print("Bill %s has no contents link" % self.billno)

        if self.amendlink:
            contents.append('<a href="%s" target="_blank">Amendments</a>' %
                            self.amendlink)

        if self.FIRlink:
            contents.append('<a href="%s" target="_blank">FIR Report</a>' %
                            self.FIRlink)

        if self.LESClink:
            contents.append('<a href="%s" target="_blank">LESC Report</a>' %
                            self.LESClink)

        if contents:
            outstr += ' &bull; '.join(contents) + '<br />'

        if self.sponsor and self.sponsorlink:
            outstr += 'Sponsor: <a href="%s" target="_blank">%s</a><br />' % \
                (self.sponsorlink, self.sponsor)

        return outstr


    def show_text(self):
        '''Show a summary of the bill's status in plaintext format.
        '''
        outstr = '%s: %s\n' % (self.billno, self.title)
        outstr += self.bill_url() + '\n'

        if self.last_action_date:
            outstr += "Last action: %s\n" % \
                self.last_action_date.strftime('%m/%d/%Y')
        else:
            outstr += "No action yet.\n"

        if self.statustext:
            outstr += 'Status: %s\n' % self.statustext

        if self.location:
            l = Committee.query.filter_by(code=self.location).first()
            outstr += 'Current location: %s <%s>' % \
                (l.name, l.get_link())
            if self.scheduled_date and self.scheduled_date > datetime.now():
                outstr += ' SCHEDULED FOR: ' \
                    + self.scheduled_date.strftime('%m/%d/%Y')
            outstr += '\n'

        outstr += 'Full text of %s: %s\n' % \
            (self.billno, self.contentslink)

        if self.amendlink:
            outstr += 'Amendments: ' + self.amendlink + '\n'

        if self.FIRlink:
            outstr += 'FIR report: ' + self.FIRlink + '\n'

        if self.LESClink:
            outstr += 'LESC report: ' + self.LESClink + '\n'

        # print('Sponsor: %s : %s' % (self.sponsor, self.sponsorlink))
        if self.sponsor:
            if self.sponsorlink:
                outstr += 'Sponsor: %s <%s>' % (self.sponsor, self.sponsorlink)
            else:
                outstr += 'Sponsor:  %s' % self.sponsor + '\n'

        return outstr


#
# Many to many relationship between Legislators and Committees
#
committee_members = db.Table('committee_members',
                             db.Column('legislator_id', db.Integer,
                                       db.ForeignKey('legislator.id'),
                                       primary_key=True),
                             db.Column('committee_id', db.Integer,
                                       db.ForeignKey('committee.id'),
                                       primary_key=True))


#
# Legislator list will be populated from
# ftp://www.nmlegis.gov/Legislator%20Information/Legislators.XLS
# Smaller, but missing crucial info like the whether the person is a
# Senator or a Representative, is
# ftp://www.nmlegis.gov/Legislator%20Information/LegislatorsCommaDelimitedforMerging.txt
#
class Legislator(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    sponcode = db.Column(db.String(9))

    lastname = db.Column(db.String(25))
    firstname = db.Column(db.String(25))
    initial = db.Column(db.String(5))

    # Senator, Representative etc.
    title = db.Column(db.String(50))

    # Contact info
    street = db.Column(db.String(50))
    city = db.Column(db.String(20))
    state = db.Column(db.String(2))
    zip = db.Column(db.String(10))

    work_phone = db.Column(db.String(25))
    home_phone = db.Column(db.String(25))
    office_phone = db.Column(db.String(25))
    email = db.Column(db.String(50))
    office = db.Column(db.String(8))

    # Comma-separated list of commmittees this legislator chairs:
    chairships = db.Column(db.String(25))

    # Things we don't care about yet, but are available in the XLS:
    # party = db.Column(db.String(1))
    # district = db.Column(db.String(4))
    # county = db.Column(db.String(15))
    # lead_posi = db.Column(db.String(5))
    # start_year = db.Column(db.String(4))


    def __repr__(self):
        return '%s: %s %s %s' % (self.sponcode, self.title,
                                 self.firstname, self.lastname)

    @staticmethod
    def refresh_legislators_list():
        '''Long-running, fetches XLS file from website,
           should not be called in user-facing code.
        '''
        for newleg in nmlegisbill.get_legislator_list():
            dbleg = Legislator.query.filter_by(sponcode=newleg['sponcode']).first()
            if (dbleg):
                for k in newleg:
                    setattr(dbleg, k, newleg[k])
            else:
                dbleg = Legislator(**newleg)
            db.session.add(dbleg)

        db.session.commit()


class Committee(db.Model):
    '''A Committee object may be a committee, or another bill destination
       such as House Floor, Governor's Desk or Dead.
    '''
    id = db.Column(db.Integer, primary_key=True)

    code = db.Column(db.String(8))

    last_check = db.Column(db.DateTime, nullable=True)

    name = db.Column(db.String(80))

    # Free-form meeting time/pkace description,
    # e.g. "Monday, Wednesday & Friday- 8:30 a.m. (Room 315)"
    mtg_time = db.Column(db.String(100))

    # When did we last check this committee?
    update_date = db.Column(db.DateTime)

    # A committee can have only one chair.
    chair = db.Column(db.Integer, db.ForeignKey('legislator.id'))

    members = db.relationship('Legislator', secondary=committee_members,
                              lazy='subquery',
                              backref=db.backref('legislators', lazy=True))

    def __repr__(self):
        return 'Committee %s: %s' % (self.code, self.name)

    def update(self):
        '''Update a committee from its web page.
        '''
        return
        print("Updating committee", self.code, "from the web")
        newcom = nmlegisbill.expand_committee(self.code)

        self.name = newcom['name']
        if 'mtg_time' in newcom:
            self.mtg_time = newcom['mtg_time']
        if 'chair' in newcom:
            self.chair = newcom['chair']

        members = []
        newbies = []
        need_legislators = False
        if 'members' in newcom:
            for member in newcom['members']:
                m = Legislator.query.filter_by(sponcode=member).first()
                if m:
                    members.append(m)
                else:
                    need_legislators = True
                    newbies.append(member)

            # If there were any sponcodes we hadn't seen before,
            # that means it's probably time to update the legislators list:
            if need_legislators:
                try:
                    Legislator.refresh_legislators_list()
                except:
                    print("Couldn't update legislators list")
                    print(traceback.format_exc())

            # Add any newbies:
            for member in newbies:
                m = Legislator.query.filter_by(sponcode=member).first()
                if m:
                    members.append(m)
                else:
                    print("Even after updating Legislators, couldn't find"
                          + member, file=sys.stdout)

        self.members = members

        # Loop over (billno, date) pairs where date is a string, 1/27/2019
        if 'scheduled_bills' in newcom:
            for billdate in newcom['scheduled_bills']:
                b = Bill.query.filter_by(billno=billdate[0]).first()
                if b:
                    b.location = self.code
                    if billdate[1]:
                        b.scheduled_date = dateutil.parser.parse(billdate[1])
                    # XXX Don't need to add(): that happens automatically
                    # when changing a field in an existing object.
                    db.session.add(b)
                else:
                    print("Not tracking bill", billdate[0])

        self.last_check = datetime.now()

        db.session.add(self)


    def get_link(self):
        if self.code == 'House' or self.code == 'Senate':
            return 'https://www.nmlegis.gov/Entity/%s/Floor_Calendar' \
                % self.code
        return 'https://www.nmlegis.gov/Committee/Standing_Committee?CommitteeCode=%s' % self.code

