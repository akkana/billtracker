from billtracker import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func

from billtracker.bills import nmlegisbill, billutils
from billtracker.emails import send_email
from billtracker.bills.nmlegisbill import update_legislative_session_list

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
    # Made more complicated by the fact that the lists will be different
    # for each session.
    # SQL doesn't have any list types, so this is a comma separated list
    # of billnumbers for each session, like this:
    # 19:SB1,SB2,HB33|19s:SB1,HB1|20:...
    # If there is no colon, it's presumed to be left over from before
    # it handled multiple sessions, and the existing data will be ignored
    # so all bills will be new again when first seen.
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

    def tracking(self, billno, yearcode=None):
        """Convenience routine to help with laying out the allbills page
        """
        if not yearcode:
            yearcode = LegSession.current_yearcode()

        bill = Bill.query.filter_by(billno=billno, year=yearcode).first()
        if not bill:
            return False
        return (bill in self.bills)

    def get_bills_seen(self, yearcode):
        if self.bills_seen:
            sessionlists = self.bills_seen.split('|')
            for sl in sessionlists:
                try:
                    seenyearcode, bills = sl.split(':')
                    if seenyearcode == yearcode:
                        return bills.split(',')
                except ValueError:
                    pass
        return []

    def update_bills_seen(self, billno_list, yearcode):
        """billno_list should be a comma-separated string.
        """
        if self.bills_seen and ':' not in self.bills_seen:
            self.bills_seen = ""

        if self.bills_seen:
            new_bills_seen = []
            sessionlists = self.bills_seen.split('|')
            for sl in sessionlists:
                seenyearcode, bills = sl.split(':')
                if seenyearcode == yearcode:
                    new_bills_seen.append(yearcode + ":" + billno_list)
                    billno_list = ""
                else:
                    new_bills_seen.append(sl)
            # Did we append billno_list? Or was it the first time
            # seeing any bills from this yearcode?
            if billno_list:
                new_bills_seen.append(yearcode + ":" + billno_list)
        else:
            new_bills_seen = [ yearcode + ":" + billno_list ]

        # Maybe later: Only keep the last three sessions worth

        self.bills_seen = '|'.join(new_bills_seen)

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


    #
    # All user bills*() functions can take an optional yearcode..
    # If not specified, will return only bills for the current
    # legislative session. If negative, will return bills from all years.
    #

    def bills_by_yearcode(self, yearcode=None):
        # XXX There has got to be a clever way to do this from the db,
        # but userbills only has user_id and bill_id.
        # thebills = db.session.query(userbills).filter_by(user_id=self.id).count()

        if not yearcode:
            yearcode = LegSession.current_yearcode()

        bill_list = []
        for bill in self.bills:
            if bill.year == yearcode:
                bill_list.append(bill)

        return bill_list

    def bills_by_number(self, yearcode=None):
        return sorted(self.bills_by_yearcode(yearcode),
                      key=Bill.bill_natural_key)

    def bills_by_action_date(self, yearcode=None):
        return sorted(self.bills_by_yearcode(yearcode),
                      key=Bill.last_action_key)

    def bills_by_status(self, yearcode=None):
        return sorted(self.bills_by_yearcode(yearcode), key=Bill.status_key)

    def show_bill_table(self, bill_list, inline=False):
        """Return an HTML string showing status for a list of bills
           as HTML table rows.
           Does not inclue the enclosing <table> or <tbody> tags.
           If inline==True, add table row colors as inline CSS
           since email can't use stylesheets.
        """
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
    """Look up the latest on a commitee and return a Committee object.
       Fetch it from the web if it doesn't exist yet or hasn't been
       updated recently, otherwise get it from the database.
       Doesn't commit the db session; the caller should do that.
    """
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

    # Year: this is really what the rest of the code calls yearcode,
    # a 2-digit string ('20') with an optional session modifier
    # ('20s2' for 2020 Special Session 2).
    # It might be worth renaming this to yearcode if a migration can do that.
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

    # Bill's sponsor codes, comma separated.
    sponsor = db.Column(db.String(20))

    # XXX URL for bill's first sponsor.
    # Not used now, better to generate list of all sponsors from the sponcodes.
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
        """Natural key, digits considered as numbers, for sorting text.
           Return a string but with the number turned into a
           leading-zeros 5-digit string.
        """
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
        """Natural key, digits considered as numbers, for sorting Bills.
        """
        return Bill.natural_key(bill.billno)


    @staticmethod
    def last_action_key(bill):
        """Sort bills by last action date, most recent first,
           with a secondary sort on billno.
           But if a bill is scheduled, put it first in the list,
           with bills that have the earliest scheduled dates first.
        """
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
            return bill.scheduled_date.strftime('0 %Y-%m-%d %H:%M') \
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
        """Sort bills by their location/status,
           with chaptered (signed) bills first, then passed bills,
           then bills on the Senate or House floors, then everything else.
        """
        # Bills that are tabled should be lower priority than active bills.
        if bill.statustext and 'tabled' in bill.statustext.lower():
            return '50' + Bill.bill_natural_key(bill)

        # Bills that are scheduled go at the top:
        if bill.scheduled_in_future():
            datestr = bill.scheduled_date.strftime('0 %Y-%m-%d %H:%M')

            # Bills on the Senate or House floors come first.
            if bill.location == 'Senate':
                return datestr + '1' + Bill.bill_natural_key(bill)

            # then House
            if bill.location == 'House':
                return datestr + '2' + Bill.bill_natural_key(bill)

            # then Committees
            return datestr + '3' + Bill.bill_natural_key(bill)

        # Bills on the Senate or House floors come first.
        if bill.location == 'Senate':
            return '20' + Bill.bill_natural_key(bill)

        if bill.location == 'House':
            return '30' + Bill.bill_natural_key(bill)

        # Bills that are passed still need some advocacy.
        if bill.location == 'Passed':
            return '60' + Bill.bill_natural_key(bill)

        # Bills that are already signed don't need further action
        # so they should come later.
        if bill.location == 'Signed':
            return '80' + Bill.bill_natural_key(bill)

        if bill.location == 'Chaptered':
            return '85' + Bill.bill_natural_key(bill)

        # Bills to list near the end: dead or not germane.
        # No point in further advocacy.

        if bill.location == 'Died':
            return '95' + Bill.bill_natural_key(bill)

        # Bills ruled not germane in a 30-day session still have a committee
        # (HXRC, at least in 2020) as location; but they have "Not Printed"
        # in their status.
        if bill.statustext and 'Not Printed' in bill.statustext:
            return '99' + Bill.bill_natural_key(bill)

        # All other bills are presumably in committee somewhere.
        # Put them after the House and Senate floors but before anything else.
        return '40' + Bill.last_action_key(bill)


    @staticmethod
    def num_tracking_billno(billno, yearcode):
        b = Bill.query.filter_by(billno=billno, year=yearcode).first()
        if not b:
            return 0
        return b.num_tracking()


    def num_tracking(self):
        """How many users are following this bill?
        """
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
        """Is a bill scheduled for a future *date*?
           If the current time is 19:00 or later, we'll consider
           a scheduled date of today to be in the past; if it's
           earlier than that, it's in the future.
           (Figuring not many committees meet later than 6pm.)
        """
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
        """Has the bill changed in the last day or two, or does it
           have impending action like a scheduled committee hearing
           or the House or Senate floor?
           Or has it changed since the user's last check if that's
           longer than a day or two?
        """
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
        return nmlegisbill.bill_url(self.billno, self.year)


    def show_html(self):
        """Show a summary of the bill's status.
        """
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
                    if self.scheduled_date.hour:
                        outstr += ' <b>SCHEDULED: %s</b>' \
                            % self.scheduled_date.strftime('%a %m/%d/%Y %H:%M')
                    else:
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
            contents.append('<a href="%s" target="_blank">Original text</a>' %
                            self.contentslink)
        else:
            print("Bill %s has no contents link" % self.billno)

        if self.amendlink:
            contents.append('<a href="%s" target="_blank">Amended</a>' %
                            self.amendlink)

        if self.FIRlink:
            contents.append('<a href="%s" target="_blank">FIR Report</a>' %
                            self.FIRlink)

        if self.LESClink:
            contents.append('<a href="%s" target="_blank">LESC Report</a>' %
                            self.LESClink)

        if contents:
            outstr += ' &bull; '.join(contents) + '<br />'

        if self.sponsor:
            outstr += 'Sponsor: ' + self.get_sponsor_links()

        return outstr


    def get_sponsor_links(self):
        """Return HTML for a list of sponsor links, each of which is like
           "https://www.nmlegis.gov/Members/Legislator?SponCode=HFIGU"
        """
        if not self.sponsor:
            return ""

        sponlinks = []
        sponcodes = self.sponsor.split(',')
        for sponcode in sponcodes:
            leg = Legislator.query.filter_by(sponcode=sponcode).first()
            if leg:
                sponlinks.append('<a href="https://www.nmlegis.gov/Members/Legislator?SponCode=%s">%s</a>'
                                 % (leg.sponcode, leg.lastname))

        return ', '.join(sponlinks)


    def show_text(self):
        """Show a summary of the bill's status in plaintext format.
        """
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
        """Long-running, fetches XLS file from website,
           should not be called in user-facing code.
        """
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
    """A Committee object may be a committee, or another bill destination
       such as House Floor, Governor's Desk or Dead.
    """
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    code = db.Column(db.String(8))

    # When did we last check this committee?
    last_check = db.Column(db.DateTime, nullable=True)

    name = db.Column(db.String(80))

    # Free-form meeting time/pkace description,
    # e.g. "Monday, Wednesday & Friday- 8:30 a.m. (Room 315)"
    mtg_time = db.Column(db.String(100))

    # NOTUSED. Could be used to indicate obsolete committees.
    update_date = db.Column(db.DateTime)

    # A committee can have only one chair.
    chair = db.Column(db.Integer, db.ForeignKey('legislator.id'))

    members = db.relationship('Legislator', secondary=committee_members,
                              lazy='subquery',
                              backref=db.backref('legislators', lazy=True))

    def __repr__(self):
        return 'Committee %s: %s' % (self.code, self.name)

    def get_meeting_time(self):
        """Try to parse the meeting time from the string mtg_time.
           Return (hour, min).
        """
        try:
            m = re.match(".*(\d{1,2}):(\d\d) ([ap]\.m\.)", self.mtg_time)
            hour = int(m.group(1))
            if m.group(3) == "p.m.":
                hour += 12
            minute = int(m.group(2))
            return hour, minute
        except:
            if self.mtg_time:
                print("Can't parse %s meeting time of '%s'" % (self.code,
                                                               self.mtg_time),
                      file=sys.stderr)
            else:
                print("%s meeting time is unknown" % self.code,
                      file=sys.stderr)

            return 0, 0

    def update_from_parsed_page(self, newcom, yearcode=None):
        """Update a committee from the web, assuming the time-consuming
           web fetch has already been done.
        """
        if not yearcode:
            yearcode = LegSession.current_yearcode()

        self.code = newcom['code']
        self.name = newcom['name']
        if 'mtg_time' in newcom:
            self.mtg_time = newcom['mtg_time']
        if 'chair' in newcom:
            chair = Legislator.query \
                              .filter_by(sponcode=newcom['chair']).first()
            if chair:
                self.chair = chair.id
            else:
                print("Couldn't get chair of", self.code, file=sys.stderr)

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
                    print("Couldn't update legislators list", file=sys.stderr)
                    print(traceback.format_exc(), file=sys.stderr)

            # Add any newbies:
            for member in newbies:
                m = Legislator.query.filter_by(sponcode=member).first()
                if m:
                    members.append(m)
                else:
                    print("Even after updating Legislators, couldn't find"
                          + member, file=sys.stderr)

        self.members = members

        updated_bills = []
        not_updated_bills = []
        # Loop over (billno, date) pairs where date is a string, 1/27/2019
        if 'scheduled_bills' in newcom:
            hour, minute = self.get_meeting_time()
            # print("Looping over scheduled bills", newcom['scheduled_bills'])
            for billdate in newcom['scheduled_bills']:
                b = Bill.query.filter_by(billno=billdate[0],
                                         year=yearcode).first()
                if b:
                    b.location = self.code
                    if billdate[1]:
                        try:
                            sched_date = dateutil.parser.parse(billdate[1])
                            sched_date = sched_date.replace(hour=hour,
                                                            minute=minute)
                            b.scheduled_date = sched_date
                            print(b, "set sched date to", sched_date)
                        except Exception as e:
                            print("Couldn't set sched_date for %s" % b.billno,
                                  file=sys.stderr)
                            print(e, file=sys.stderr)
                    # XXX Don't need to add(): that happens automatically
                    # when changing a field in an existing object.
                    db.session.add(b)
                    updated_bills.append(str(b))
                else:
                    not_updated_bills.append(billdate[0])

        self.last_check = datetime.now()

        db.session.add(self)
        db.session.commit()

        print("Updated bills", ', '.join(updated_bills))
        print("Skipped bills not in the db", ', '.join(not_updated_bills))


    def refresh(self):
        """Refresh a committee from its web page.
        """
        return
        print("Committee.refresh: Updating committee", self.code,
              file=sys.stderr)
        newcom = nmlegisbill.expand_committee(self.code)
        self.update_from_parsed_page(newcom)


    def get_link(self):
        if self.code == 'House' or self.code == 'Senate':
            return 'https://www.nmlegis.gov/Entity/%s/Floor_Calendar' \
                % self.code
        return 'https://www.nmlegis.gov/Committee/Standing_Committee?CommitteeCode=%s' % self.code


class LegSession(db.Model):
    # The integer session id used by nmlegis.
    id = db.Column(db.Integer, primary_key=True, unique=True)

    # The yearcode that corresponds to User.year: e.g. "20s2".
    # No real need to crossreference the objects, though.
    yearcode = db.Column(db.String(8))

    # Year of the session, as an integer
    year = db.Column(db.Integer)

    # Typename of the session, e.g. "Regular" or "2nd Special"
    typename = db.Column(db.String(16))

    def __repr__(self):
        return "LegSession(id=%d, %04d %s)" % (self.id, self.year,
                                               self.typename)

    @staticmethod
    def current_leg_session():
        """Return the currently running (or most recent) legislative session
           (which is the session with the highest id).
        """
        try:
            max_id = db.session.query(func.max(LegSession.id)).scalar()
            return LegSession.query.get(max_id)
        except:
            return None

    @staticmethod
    def current_yearcode():
        return LegSession.current_leg_session().yearcode

    @staticmethod
    def by_yearcode(yearcode):
        return LegSession.query.filter_by(yearcode=yearcode).first()

    @staticmethod
    def update_session_list():
        """Long running query that fetches the (possibly cached)
           Legislation_List (same file used for allbills) and adds
           any new sessions that might have appeared.
           Called from /api/refresh_session_list.
        """
        # Update the session list from nmlegisbill
        sessionsdict = update_legislative_session_list()
        # A list of dicts including id, year, typename, yearcode
        # frmo nnmlegisbill.

        for lsess in sessionsdict:
            # Is it in the database? Then we can stop: sessions
            # in Legislation_List are listed in reverse chronological,
            # so if we have this one we have everything after it.
            if LegSession.query.get(lsess["id"]):
                break

            newsession = LegSession(id=lsess["id"],
                                    year = lsess["year"],
                                    yearcode = lsess["yearcode"],
                                    typename = lsess["typename"])
            db.session.add(newsession)

        db.session.commit()

    def sessionname(self):
        """Return the full session name, e.g. "2020 2nd Special"
        """
        return "%4d %s" % (self.year, self.typename)

    def long_url_code(self):
        """Return the string that goes in the URL for analysis like FIR
           reports, which use a code like "20 Regular", "20 Special" or
           "20 Special2" (with space replaced with %20).
        """
        return nmlegisbill.yearcode_to_longURLcode(self.year)
