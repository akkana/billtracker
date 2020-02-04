from billtracker import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from billtracker.bills import nmlegisbill, billutils
from billtracker.emails import send_email

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
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), nullable=True)
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

    def tracking(self, billno, leg_year=None):
        '''Convenience routine to help with laying out the allbills page
        '''
        if not leg_year:
            leg_year = billutils.current_leg_year()
        yearstr = billutils.year_to_2digit(leg_year)

        bill = Bill.query.filter_by(billno=billno, year=yearstr).first()
        if not bill:
            return False
        return (bill in self.bills)

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


    # All user bills*() functions can take an optional year.
    # If not specified, will return only bills for the current
    # legislative year. If negative, will return bills from all years.
    def bills_by_year(self, year=None):
        # XXX There has got to be a clever way to do this from the db,
        # but userbills only has user_id and bill_id.
        # thebills = db.session.query(userbills).filter_by(user_id=self.id, ).count()

        if not year:
            year = billutils.current_leg_year()

        elif type(year) is int and year < 0:
            return self.bills

        yearstr = billutils.year_to_2digit(year)

        bill_list = []
        for bill in self.bills:
            if bill.year == yearstr:
                bill_list.append(bill)

        return bill_list


    def bills_by_number(self, year=None):
        return sorted(self.bills_by_year(year), key=Bill.bill_natural_key)


    def bills_by_action_date(self, year=None):
        return sorted(self.bills_by_year(year), key=Bill.last_action_key)


    def bills_by_status(self, year=None):
        return sorted(self.bills_by_year(year), key=Bill.status_key)


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
    comm.refresh()
    return comm


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

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

    # Year, a 2-digit string, '19', not '2019' or 2019
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

    # We'll seldom need to know users for a bill, so no need to
    # include it as a line here.
    # user = db.relationship('User', secondary=userbills, lazy='subquery',
    #                         backref=db.backref('bills', lazy=True))

    def __repr__(self):
        return 'Bill %s %s' % (self.billno, self.year)

    @staticmethod
    def natural_key(billno):
        '''Natural key, digits considered as numbers, for sorting text.
           Return a string but with the number turned into a
           leading-zeros 5-digit string.
        '''
        # return [ Bill.a2order(c) for c in re.split('(\d+)', text) ]
        for i, c in enumerate(billno):
            if c.isdigit():
                return '%s%05d' % (billno[:i], int(billno[i:]))

        # No digits, which shouldn't happen
        return billno

    @staticmethod
    def a2order(billno):
        return Bill.natural_key(billno)

    @staticmethod
    def bill_natural_key(bill):
        '''Natural key, digits considered as numbers, for sorting Bills.
        '''
        return Bill.natural_key(bill.billno)


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
        # However, a scheduled date is just a day (time is 00:00:00);
        # if it's morning, it's crucially important to see bills
        # scheduled for today, but by evening, they're less interesting
        if bill.scheduled_in_future():
            # This starts with 0 so it will always come first:
            return bill.scheduled_date.strftime('0 %Y-%m-%d') \
                + Bill.a2order(bill.billno)

        # Bills with no last_action_date come last.
        if not bill.last_action_date:
            return '9 ' + Bill.a2order(bill.billno)

        # There's definitely a last_action_date.
        # But if there's a scheduled_date that's more recent,
        # use that as the last action:
        lastaction = bill.last_action_date
        if bill.scheduled_date and bill.scheduled_date > lastaction:
            lastaction = bill.scheduled_date

        # Sort by the last action in reverse order:
        # so later dates return an earlier key.
        # It's hard to reverse a datetime, but it's easy with Unix time.
        lastaction = bill.last_action_date
        if not lastaction or (bill.scheduled_date and
                              bill.scheduled_date > lastaction):
            lastaction = bill.scheduled_date
        # Need to reverse the date, so later dates return an
        # earlier key. This will start with a digit other than 0.
        return '2 %010d' % (2000000000 -
                            time.mktime(lastaction.timetuple())) \
            + Bill.a2order(bill.billno)


    @staticmethod
    def status_key(bill):
        '''Sort bills by their location/status,
           with chaptered (signed) bills first, then passed bills,
           then bills on the Senate or House floors, then everything else.
        '''
        if bill.location == 'Chaptered':
            return '10' + Bill.bill_natural_key(bill)

        if bill.location == 'Signed':
            return '15' + Bill.bill_natural_key(bill)

        if bill.location == 'Passed':
            return '20' + Bill.bill_natural_key(bill)

        if bill.location == 'Senate':
            return '30' + Bill.bill_natural_key(bill)

        if bill.location == 'House':
            return '40' + Bill.bill_natural_key(bill)

        if bill.location == 'Died':
            return '50' + Bill.bill_natural_key(bill)

        # Bills ruled not germane in a 30-day session have "Not Printed"
        # in their status. They should be listed last since they won't
        # be considered.
        if 'Not Printed' in bill.statustext:
            return '99' + Bill.bill_natural_key(bill)

        return '60' + Bill.last_action_key(bill)


    @staticmethod
    def num_tracking_billno(billno, leg_year):
        yearstr = billutils.year_to_2digit(leg_year)

        b = Bill.query.filter_by(billno=billno, year=yearstr).first()
        if not b:
            return 0
        return b.num_tracking()


    def num_tracking(self):
        '''How many users are following this bill?
        '''
        # select COUNT(*) from userbills where bill_id=self.id;
        # How to query a Table rather than a Model:
        return db.session.query(userbills).filter_by(bill_id=self.id).count()


    def users_tracking(self):
        userlist = []
        tracking = db.session.query(userbills).filter_by(bill_id=self.id).all()
        for u in tracking:
            userlist.append(User.query.filter_by(id=u.user_id).first())
        return userlist


    def scheduled_in_future(self):
        '''Is a bill scheduled for a future *date*?
           If the current time is 19:00 or later, we'll consider
           a scheduled date of today to be in the past; if it's
           earlier than that, it's in the future.
           (Figuring not many committees meet later than 6pm.)
        '''
        now = datetime.now()
        nowdate = datetime.date(now)
        if now.hour >= 19:
            nowdate += timedelta(days=1)

        if self.scheduled_date:
            scheddate = datetime.date(self.scheduled_date)
            if scheddate >= nowdate:
                return True


    def set_from_parsed_page(self, b):
        # For location, there's a name change,
        # and if the committee changes, also clear scheduled_date.
        # Do that first, to ensure we don't set scheduled_date and
        # then later clear it.
        if 'curloc' in b:
            self.location = b['curloc']
            self.scheduled_date = None

        for k in b:
            if k == 'curloc':
                continue

            # Mysteriously, the converse of setattr is __getattribute__;
            # Bill has no setattr() though the python 3.7.2 docs say there
            # should be. (Maybe that means db.Model is an old-style class?)
            if self.__getattribute__(k) != b[k]:
                setattr(self, k, b[k])

        self.update_date = datetime.now()


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


    # Jinja templates can't import nmlegisbill;
    # they need a method that's part of the model.
    def bill_url(self):
        return nmlegisbill.bill_url(self.billno)


    def show_html(self):
        '''Show a summary of the bill's status.
        '''
        outstr = '<b><a href="%s" target="_blank">%s: %s</a></b><br />' % \
            (self.bill_url(), self.billno, self.title)

        if self.location:
            comm = Committee.query.filter_by(code=self.location).first()
            if comm:
                if comm.name == 'House' or comm.name == 'Senate':
                    outstr += '<b class="highlight">Location: <a href="%s" target="_blank">%s Floor</a></b>' % \
                        (comm.get_link(), comm.name)
                else:
                    outstr += 'Location: <a href="%s" target="_blank">%s</a>' % \
                        (comm.get_link(), comm.name)

            else:        # A location that has no committee entry
                outstr += 'Location: %s<br />' % self.location

            # The date to show is the most recent of last_action_date
            # or scheduled_date.
            last_action = self.last_action_date

            if self.scheduled_date:
                future = self.scheduled_in_future()
                sched_date = datetime.date(self.scheduled_date)
                today = datetime.date(datetime.now())

                # If the bill is scheduled in the future, bold it:
                if future:
                    outstr += ' <b>SCHEDULED: %s</b>' \
                        % self.scheduled_date.strftime('%a %m/%d/%Y')

                # if it's not considered future but still today,
                # highlight that:
                elif sched_date == today:
                    outstr += ' Was scheduled today, %s' \
                        % self.scheduled_date.strftime('%a %m/%d/%Y')

                # otherwise show the most recent of scheduled or last_action
                elif (self.last_action_date
                      and self.last_action_date > self.scheduled_date):
                    outstr += ' Last action: %s' % \
                        self.last_action_date.strftime('%a %m/%d/%Y')
                else:
                    outstr += ' (Last scheduled: %s)' \
                        % sched_date.strftime('%a %m/%d/%Y')
                outstr += '<br />'

        else:            # No location set
            outstr += 'Location: unknown<br />'

        if self.last_action_date:
            outstr += " Last action: %s<br />" % \
                self.last_action_date.strftime('%a %m/%d/%Y')

        # Bills don't have action dates on signing:
        elif not self.statustext or not self.statustext.startswith('Signed'):
            outstr += " No action yet.<br />"

        if self.statustext:
            # statusHTML is full of crap this year, so prefer statustext
            # even in HTML output until/unless I find a way around that.

            # But first, pull the action code out of statustext
            # to be dealt with separately.
            if '\n' in self.statustext:
                lines = self.statustext.split('\n')
                # Is it really an action code? Or just the last line
                # of normal actiontext?
                actioncode = lines[-1]
                if '[' in actioncode:
                    statustext = ', '.join(lines[:-1])
                else:
                    statustext = ', '.join(lines)
                    actioncode = ''
            else:
                statustext = self.statustext.strip()
                actioncode = ''

            if statustext:
                outstr += 'Status: %s<br />\n' % statustext
            if actioncode:
                outstr += '<a href="https://www.nmlegis.gov/Legislation/' \
                          'Action_Abbreviations">Full history</a>: ' \
                          '<span class="historycode" title="%s">%s</span>' \
                          '<br />\n' \
                              % (nmlegisbill.decode_full_history(actioncode),
                                 actioncode)

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
                self.last_action_date.strftime('%a %m/%d/%Y')
        # Bills don't have action dates on signing:
        elif not self.statustext or not self.statustext.startswith('Signed'):
            print(self.billno, "NO STATUSTEXT!")
            outstr += "No action yet.\n"

        if self.location:
            comm = Committee.query.filter_by(code=self.location).first()
            if comm:
                outstr += 'Location: %s <%s>' % \
                    (comm.name, comm.get_link())
            else:
                outstr += 'Location: %s' % self.location

            # The date to show is the most recent of last_action_date
            # or scheduled_date.
            last_action = self.last_action_date

            if self.scheduled_date:
                future = self.scheduled_in_future()
                sched_date = datetime.date(self.scheduled_date)
                today = datetime.date(datetime.now())

                # If the bill is scheduled in the future, bold it:
                if future:
                    outstr += ' SCHEDULED: %s' \
                        % self.scheduled_date.strftime('%a %m/%d/%Y')

                # if it's not considered future but still today,
                # highlight that:
                elif sched_date == today:
                    outstr += ' Was scheduled today, %s' \
                        % self.scheduled_date.strftime('%a %m/%d/%Y')

                # otherwise show the most recent of scheduled or last_action
                elif (self.last_action_date
                      and self.last_action_date > self.scheduled_date):
                    outstr += ' Last action: %s' % \
                        self.last_action_date.strftime('%a %m/%d/%Y')
                else:
                    outstr += ' (Last scheduled: %s)' \
                        % sched_date.strftime('%a %m/%d/%Y')

            # If it's on the House or Senate floor, highlight that:
            if self.location == 'House' or self.location == 'Senate':
                outstr += ' ** %s Floor **' % self.location
            outstr += '\n'

        else:
            outstr += 'Location: unknown\n'

        if self.statustext:
            outstr += 'Status: %s\n' % self.statustext

        outstr += 'Text of %s: %s\n' % \
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
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

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
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

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


    def update_from_parsed_page(self, newcom):
        '''Update a committee from the web, assuming the time-consuming
           web fetch has already been done.
        '''
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

        updated_bills = []
        not_updated_bills = []
        # Loop over (billno, date) pairs where date is a string, 1/27/2019
        if 'scheduled_bills' in newcom:
            print("Looping over scheduled bills", newcom['scheduled_bills'])
            for billdate in newcom['scheduled_bills']:
                b = Bill.query.filter_by(billno=billdate[0]).first()
                if b:
                    b.location = self.code
                    if billdate[1]:
                        b.scheduled_date = dateutil.parser.parse(billdate[1])
                    # XXX Don't need to add(): that happens automatically
                    # when changing a field in an existing object.
                    db.session.add(b)
                    updated_bills.append(b.billno)
                else:
                    not_updated_bills.append(billdate[0])

        self.last_check = datetime.now()

        db.session.add(self)

        print("Updated bills", ', '.join(updated_bills))
        print("Skipped bills", ', '.join(not_updated_bills))


    def refresh(self):
        '''Refresh a committee from its web page.
        '''
        return
        print("Updating committee", self.code, "from the web")
        newcom = nmlegisbill.expand_committee(self.code)
        self.update_from_parsed_page(newcom)


    def get_link(self):
        if self.code == 'House' or self.code == 'Senate':
            return 'https://www.nmlegis.gov/Entity/%s/Floor_Calendar' \
                % self.code
        return 'https://www.nmlegis.gov/Committee/Standing_Committee?CommitteeCode=%s' % self.code

