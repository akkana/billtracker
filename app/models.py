
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func

from app import db, login
from app.bills import nmlegisbill, billutils, decodenmlegis
from app.emails import send_email
from app.bills.nmlegisbill import update_legislative_session_list

from datetime import datetime, date, timedelta, timezone
import dateutil.parser
import time
import re
import random
import traceback
import sys


# Many-to-many relationship between users and bills requires
# (or at least recommends) a association table,
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

    # List of bills the user cares about (many to many).
    # lazy='subquery' makes user.bills be a list of bills.
    # lazy='dynamic' makes user.bills be a query, so you can
    # modify it with further filter_by calls like
    # self.bills.filter_by(year=yearcode),
    # but then you have to append .all() whenever you use it.
    bills = db.relationship('Bill', secondary=userbills, lazy='subquery',
                            backref=db.backref('users', lazy=True))

    # List of bill IDs the user has seen in the most recent session.
    # These bills may not even be in the database, but they've been on
    # the "all bills" list so the user has had a chance to review them.
    #
    # The bill list changes with each session, but new/seen bills only
    # make sense for the latest session -- it's the only session for
    # which bills are still being added. But there needs to be a way
    # to detect when a new session has started. So bills_seen is
    # a string like this, starting with the yearcode::
    #   21: HB1,HB2,HB3,HB5, ...
    #
    # Previously, it stored multiple yearcodes at once, separated by |
    # so there's some legacy code to eliminate all but the latest yearcode.
    bills_seen = db.Column(db.String())

    # Comma-separated list of sponcodes for legislators this user
    # might want to contact:
    legislators = db.Column(db.String())

    # When did the user check in last?
    last_check = db.Column(db.DateTime, nullable=True)

    AUTH_CODE_CONFIRMED = "Confirmed"

    def __repr__(self):
        return '<User %s (%d)>' % (self.username, self.id)

    @staticmethod
    def remove_from_bills_seen(bill_list, yearcode):
        """Remove a bill from the bills_seen of ALL users.
        """
        print(self, "has changed! Updating bills_seen for all users",
              file=sys.stderr)

        # Query all the users who have bills_seen in this yearcode
        # yearpat = "%%%s%%" % yearcode
        # Query all users whose bills_seen starts with this yearcode.
        yearpat = "%s:%%" % (yearcode)
        for u in User.query.filter(User.bills_seen.like(yearpat)).all():
            u.remove_from_bills_seen(bill_list, self.year)

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
        """Which billnos has the user already seen on the allbills page?
           Return a list of billno strings.
        """
        if not self.bills_seen:
            return []

        # bills_seen isn't | separated any more, but do this
        # in case of a user who hasn't been updated since they were.
        sessionlists = self.bills_seen.split('|')
        for sl in sessionlists:
            try:
                seenyearcode, bills = sl.split(':')
                if seenyearcode == yearcode:
                    return bills.split(',')
            except ValueError:
                pass

        # Got here, probably a parse problem: maybe the yearcode
        # is missing and it's just a comma separated list of billnos.
        # Or maybe the given yearcode isn't the most recent: we only store
        # bills_seen for the latest yearcode.
        # Return the last list of bills.
        if sl and ':' not in sl:
            print("No colon in bills_seen for %s: %s"
                  % (self.username, self.bills_seen), file=sys.stderr)
            return sl.split(',')

        # No bills seen for this yearcode.
        if self.bills_seen:
            print("%s has bills_seen but not for session %s"
                  % (self.username, yearcode), file=sys.stderr)
        return []

    def remove_from_bills_seen(self, billno_list, yearcode):
        """Remove the given billnos from all users' bills_seen.
           For instance, if a dummy bill's title changes to a real title,
           users should see it again.
        """
        if not self.bills_seen:
            return
        if yearcode not in self.bills_seen:
            return

        billno_list = self.get_bills_seen(yearcode)
        if billno not in billno_list:
            return

        print("Removing %s from %s bills_seen" % (billno, self.username),
              file=sys.stderr)
        billno_list.remove(billno)
        self.update_bills_seen(','.join(billno_list), yearcode)
        db.session.add(self)

    def add_to_bills_seen(self, bill_list, yearcode):
        seen = self.get_bills_seen(yearcode)
        seen += bill_list
        seen.sort()
        self.update_bills_seen(','.join(seen), yearcode)
        db.session.add(self)

    def update_bills_seen(self, billno_list, yearcode):
        """billno_list should be a comma-separated string.
        """
        # Don't update with an earlier yearcode than is currently there.
        # A user shouldn't lose all their bills_seen info just because
        # they wanted to view all_bills from a previous session.
        # But if there's nothing from the current session, it's okay
        # to keep updating an earlier session (useful for unit tests).
        try:
            latest_session_seen, curlist = self.bills_seen.split(":")
            if LegSession.earlier_than(yearcode, latest_session_seen):
                print("Refusing to update bills_seen for yearcode", yearcode,
                      file=sys.stderr)
                return
        except:
            # Probably there's no session specified in billno_list.
            # Accept the update.
            if self.bills_seen:
                print("Eek, not sure of the latest session seen for %s: %s..."
                      % (self.username, self.bills_seen[:5]), file=sys.stderr)

        self.bills_seen = "%s:%s" % (yearcode, billno_list)
        db.session.add(self)

    def send_confirmation_mail(self, baseurl):
        authcode = ''
        for i in range(5):
            charset = 'abcdefghijklmnopqrstuvwxyz' \
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_'
            codelen = 20
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

        print("Sending confirmation email to", self.email,
              "with code", self.auth_code, file=sys.stderr)
        send_email("New Mexico Bill Tracker Confirmation",
                   "noreply@nmbilltracker.com",
                   [ self.email ],
                   """
Someone (hopefully you) registered your email for a new account on
the New Mexico Bill Tracker, or changed your email address there.

Username: %s
Email:    %s

Please confirm your email address so you can get daily updates about
bills that have changed by following this link:

%sconfirm_email/%s

If this was done by someone else using your email address, please
accept our apologies, and don't click the confirmation link.

""" % (self.username, self.email, baseurl, self.auth_code))


    def update_last_check(self):
        self.last_check = datetime.now()
        db.session.commit()
        # So this can be called from a template:
        return ''


    #
    # All user bills*() functions can take an optional yearcode..
    # If not specified, will return only bills for the current
    # legislative session. If negative, will return bills from all years.
    # Optional sortkey is a string, "action_date", "status", "passed".
    #

    def bills_by_yearcode(self, yearcode=None, sort_type=None):
        if not yearcode:
            yearcode = LegSession.current_yearcode()

        # Here's how to do a join query that also filters by attributes:
        bill_list = db.session.query(Bill) \
                              .join(userbills) \
                              .join(User) \
                              .filter(User.id == self.id) \
                              .filter(Bill.year == yearcode) \
                              .all()
        if sort_type:
            bill_list.sort(key=Bill.get_sort_key(sort_type))

        return bill_list


@login.user_loader
def load_user(id):
    # Some package related to flask sqlalchemy is very sensitive to
    # how to get a db object by id. With the same version of both
    # sqlalchemy and flask-sqlalchemy, one machine needs the first
    # syntax, another needs the second.
    try:
        return db.session.get(User, int(id))
    except AttributeError:
        return User.query.get(int(id))


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

    # Is the bill scheduled to come up for debate? An unaware datetime.
    # Needs to be unaware because attempting to store the local tz
    # in the database doesn't work reliably.
    scheduled_date = db.Column(db.DateTime)

    # Tags: defined by users, comma separated
    tags = db.Column(db.String(150))

    # We'll seldom need to know users for a bill, so no need to
    # include it as a line here.
    # user = db.relationship('User', secondary=userbills, lazy='subquery',
    #                         backref=db.backref('bills', lazy=True))

    def __repr__(self):
        return '<Bill %s %s>' % (self.billno, self.year)

    def get_PDF_link(self):
        if self.contentslink:
            return self.contentslink.replace(".html", ".pdf")
        return ""

    #
    # Sort keys for bills
    #

    # Default sort is natural_key, if no other key is specified
    def __lt__(self, other):
        return Bill.natural_key(self) < Bill.natural_key(other)

    @staticmethod
    def get_sort_key(sort_type):
        """Choose a sort key according to a string sort type,
           which may be "action_date", "status", or "passed".
           This allows jinja and email functions that don't have access
           to the model classes to specify sort keys.
        """
        if sort_type == "status":
            return Bill.status_key
        elif sort_type == "passed":
            return Bill.passed_key
        elif sort_type == "action_date":
            return Bill.last_action_key
        else:
            return Bill.natural_key

    @staticmethod
    def natural_key(billno):
        """Natural key, digits considered as numbers, for sorting text.
           Return a string but with the number turned into a
           leading-zeros 5-digit string.
        """
        if type(billno) is Bill:
            billno = billno.billno

        # return [ Bill.a2order(c) for c in re.split('(\d+)', text) ]

        try:
            letters, zeroes, num = nmlegisbill.billno_pat.match(billno).groups()
            number = int(num)
            return '%s%05d' % (letters, number)

        except Exception as e:
           print("billno", billno, "didn't match billno_pat:", e)
           return 'z' + billno

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
        # Bills with no last_action_date go to the end of the list.
        if not bill.last_action_date:
            return '9 ' + Bill.a2order(bill.billno)

        # There's definitely a last_action_date.
        # Sort by the last action in reverse order,
        # so later dates return an earlier key.
        # It's hard to reverse a datetime, but it's easy with Unix time.
        # Need to reverse the date, so later dates return an
        # earlier key. This will start with a digit other than 0.
        return '1 %010d' \
            % (2000000000 - time.mktime(bill.last_action_date.timetuple())) \
            + Bill.a2order(bill.billno)

    @staticmethod
    def status_key(bill):
        """Sort bills by their location/status,
           with chaptered (signed) bills first, then passed bills,
           then bills on the Senate or House floors, then everything else.
           This is the default sort on the home page.
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
    def passed_key(bill):
        """A sort key that gives precedence to bills that have passed.
        """
        if bill.location == 'Constitutional Amendment':
            return '09 ' + Bill.bill_natural_key(bill)
        if bill.location == 'Chaptered':
            return '10 ' + Bill.bill_natural_key(bill)
        if bill.location == 'Signed':
            return '20 ' + Bill.bill_natural_key(bill)
        if bill.location == 'Passed':
            return '30 ' + Bill.bill_natural_key(bill)
        if bill.location == 'Senate':
            return '40 ' + Bill.bill_natural_key(bill)
        if bill.location == 'House':
            return '50 ' + Bill.bill_natural_key(bill)
        return '90 '+ Bill.bill_natural_key(bill)

    #
    # Some utilities relating to users tracking bills
    #

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

        # Another way to do this (not sure if it's any more efficient):
        # db.session.query(User) \
        #     .join(userbills) \
        #     .join(Bill) \
        #     .filter(Bill.billno==self.billno) \
        #     .filter(Bill.year==self.year) \
        #     .all()

        return userlist


    def scheduled_in_future(self):
        """Is a bill scheduled for a future *date*?
           If the current time is 18:00 or later, we'll consider
           a scheduled date of today to be in the past; if it's
           earlier than that, it's in the future.
           (Figuring not many committees meet later than 6pm.)
        """
        now = datetime.now()
        nowdate = now.date()
        if now.hour >= 18:
            nowdate += timedelta(days=1)


        if self.scheduled_date:
            # self.scheduled_date is actually a datetime, despite the name
            if self.scheduled_date.date() >= nowdate:
                return True

    def set_from_parsed_page(self, b):
        """b is a bill dictionary coming from nmlegisbill.parse_bill_page().
           Set this Bill's values according to what was on the page.
           Calls bill_info which may update the allbills JSON.
        """
        now = datetime.now()

        # If the name changes, it was probably a dummy bill.
        # But don't worry about updating bills_seen: that should
        # be handled from allbills.
        if self.title and self.title != b['title']:
            print(self, "title changed to '%s'\n  from '%s'"
                  % (b['title'], self.title), file=sys.stderr)
            self.title = b['title']

            # A name change should also update the last action date.
            b["last_action_date"] = now
            db.session.add(self)

        # If the committee changes, also set scheduled_date
        # to include the committee's meeting time.
        # Do that first, to ensure we don't set scheduled_date and
        # then later overwrite it.
        if 'curloc' in b:
            self.location = b['curloc']

            # If the bill's scheduled date hasn't been filled in yet,
            # but the parsed page has one, copy it.
            # The scheduled date in bill pages isn't very reliable
            # and only has date, not time, but it's better than nothing.
            # The most reliable info is in the PDF calendars
            # which are updated when updating all committees.
            if not self.scheduled_date and \
               'scheduled_date' in b and b['scheduled_date']:
                self.scheduled_date = b['scheduled_date']

        for k in b:
            if k == 'curloc' or k == 'scheduled_date':
                # Already handled, skip.
                continue

            # Mysteriously, the converse of setattr is __getattribute__;
            # Bill has no setattr() though the python 3.7.2 docs say there
            # should be. (Maybe that means db.Model is an old-style class?)
            if self.__getattribute__(k) != b[k]:
                setattr(self, k, b[k])

        # Supplement those with fields from the allbills JSON
        self.update_links_from_allbills()

        self.update_date = now


    def update_links_from_allbills(self):
        # Update fields that might be in the allbills JSON (bill_info)
        # and not in the bill's actual page.
        leg_session = LegSession.by_yearcode(self.year)
        if not leg_session:
            print("Couldn't get session by yearcode", self.year)
            return
        bill_info = nmlegisbill.bill_info(self.billno, self.year,
                                          leg_session.id)

        if bill_info:
            if 'FIR' in bill_info:
                self.FIRlink = bill_info['FIR']
            if 'LESC' in bill_info:
                self.LESClink = bill_info['LESC']
            if 'Amendments_In_Context' in bill_info:
                self.amendlink = bill_info['Amendments_In_Context']
            elif 'comm_sub_links' in bill_info:
                self.amendlink = bill_info['comm_sub_links'][0][0]
            elif 'Floor_Amendments' in bill_info:
                self.amendlink = bill_info['Floor_Amendments']
        else:
            print("no bill_info, billno =", self.billno, file=sys.stderr)


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
            if not self.last_action_date:
                return False
            if not user.last_check:
                return True
            if not user.last_check:
                return True
            user.last_check = user.last_check
            if self.last_action_date > user.last_check:
                return True

        if datetime.now() - self.last_action_date < RECENT:
            return True

        return False


    # Jinja templates can't import nmlegisbill;
    # they need a method that's part of the model.
    def bill_url(self):
        return nmlegisbill.bill_url(self.billno, self.year)


    def overview_url(self):
        return nmlegisbill.bill_overview_url(self.billno, self.year)


    def show_html(self):
        """Show a summary of the bill's status, as seen on a user's home page.
        """
        outstr = '<b><a href="%s" target="_blank">%s: %s</a></b>' % \
            (self.bill_url(), self.billno, self.title)

        if self.year == LegSession.current_yearcode():
            outstr += " (<a href='%s' target='_blank'>NMLegisWatch</a>)" \
                % nmlegisbill.bill_overview_url(self.billno, self.year)

        outstr += '<br />'

        # The date to show is the most recent of last_action_date
        # or scheduled_date.
        last_action = self.last_action_date
        if last_action:
            last_action = last_action.replace(tzinfo=None)

        def highlight_if_recent(adate, pre_string):
            if adate and \
               ((now - adate) < timedelta(hours=30)):
                return "<b>%s %s</b>" % (pre_string,
                                         adate.strftime('%a %m/%d/%Y'))
            else:
                return "%s %s" % (pre_string,
                                  adate.strftime('%a %m/%d/%Y'))

        if self.location:
            comm = Committee.query.filter_by(code=self.location).first()
            if comm:
                outstr += 'Location: ' \
                          '<a href="%s" target="_blank">%s</a><br />' % \
                          (comm.get_link(), comm.name)

            else:        # A location that has no committee entry
                outstr += 'Location: %s<br />' % self.location

            now = datetime.now()
            today = now.date()

            if self.scheduled_date:
                sched_date = self.scheduled_date.date()

                future = self.scheduled_in_future()

                # If the bill is scheduled in the future, bold it:
                if future:
                    outstr += ' <b class="highlight">'
                    if self.scheduled_date.hour \
                       and (not comm or not comm.mtg_time):
                        outstr += 'SCHEDULED: %s</b><br />' \
                          % (self.scheduled_date.strftime(
                              '%a %m/%d/%Y %H:%M'))
                    elif comm and comm.mtg_time:
                        outstr += 'SCHEDULED: %s %s</b><br />' \
                          % (self.scheduled_date.strftime(
                              '%a %m/%d'), comm.mtg_time)
                    else:
                        outstr += 'SCHEDULED: %s</b><br />' \
                          % (self.scheduled_date.strftime('%a %m/%d'))

                    outstr += '</b>'

                # if it's not considered future but still today,
                # highlight that:
                elif sched_date == today:
                    outstr += ' Was scheduled today, %s<br />' \
                        % self.scheduled_date.strftime('%a %m/%d/%Y')

                # otherwise show the most recent of scheduled or last_action,
                # and highlight it if it's recent.
                elif last_action:
                    if last_action > self.scheduled_date.replace(tzinfo=None):
                        outstr += highlight_if_recent(last_action,
                                                      "Last action")
                    else:
                        outstr += highlight_if_recent(last_action,
                                                      "Last scheduled")
                    outstr += '<br />'

        else:            # No location set
            outstr += 'Location: unknown<br />'

        bill_info = nmlegisbill.bill_info(self.billno, self.year,
                                          LegSession.by_yearcode(self.year).id)
        # Currently, this is only used to detect tabled bills,
        # but eventually I hope it can be used for everything.
        # XXX Tabled info should be in the database somehow.

        if self.last_action_date:
            outstr += highlight_if_recent(last_action, "Last action")

        # Bills don't have action dates on signing:
        # elif not self.statustext or not self.statustext.startswith('Signed'):
        #     outstr += " No action yet."

        if bill_info and "tabled" in bill_info and bill_info["tabled"]:
            outstr += " <b>MAY BE TABLED</b> "

        outstr += '<br />'

        if self.statustext:
            # statusHTML is full of crap this year, so prefer statustext
            # even in HTML.

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

            statustext = statustext.strip()
            if actioncode:
                location, status, fullhist = \
                    decodenmlegis.decode_full_history(actioncode)
                if not statustext:
                    # A bill updated from the accdb will have an action code,
                    # but no status text. Take statustext from the last day
                    # of the action code.
                    statustext = fullhist[1]
            outstr += 'Status: '
            outstr += '<a target="_blank" title="Vote history" ' \
                'href="/votes/%s/%s">[Votes]</a> ' % (self.billno, self.year)
            if statustext:
                outstr += '%s<br />\n' % statustext
            if actioncode:
                hist_str = decodenmlegis.full_history_text(fullhist)
                outstr += '<a href="https://www.nmlegis.gov/Legislation/' \
                  'Action_Abbreviations" target="_blank">Full history</a>: ' \
                          '<span class="historycode" title="%s">%s</span>' \
                          '<br />\n' \
                          % (hist_str, actioncode)

                # add a progress graph
                past_locs, future_locs = \
                    decodenmlegis.get_location_lists(self.billno, fullhist)
                # print(self.billno, "past_locs:", past_locs)
                # print("   future_locs:", future_locs)

                total_steps = len(past_locs) + len(future_locs)
                # If there are any H??? or S???, count those double
                # since most bills will be assigned at least 2 committees
                if 'H???' in future_locs:
                    total_steps += 1
                if 'S???' in future_locs:
                    total_steps += 1
                stepsize = int(100. / total_steps)

                outstr += '''<table class="progress" style="width: 100%;">
<tr class="progress-gradient">\n'''
                for loc in past_locs:
                    # Temporary, just for proof of concept
                    outstr += '<td class="gradpiece" title="%s" ' % loc
                    outstr += 'style="width: %d%%">%s</td>' % (stepsize, loc)
                for loc in future_locs:
                    outstr += '<td class="notpassed" title="%s" ' % loc
                    outstr += 'style="width: %d%%">%s</td>' % (stepsize, loc)

                outstr += '</tr></table>\n'

        elif self.statusHTML:
            # not likely to be used, to have statusHTML but no statustext
            outstr += 'Status: %s<br />\n' % self.statusHTML

        contents = []
        if self.contentslink:
            contents.append('<a href="%s" target="_blank">Original text</a>' %
                            self.contentslink)
            contents.append('<a href="%s" target="_blank">PDF</a>' %
                            self.contentslink.replace(".html", ".pdf"))
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
            outstr += 'Sponsor: ' + self.get_sponsor_links() + '<br />'

        if self.tags:
            outstr += "Tags: " + self.tags

        return outstr

    def get_sponsor_links(self, html=True):
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
                if html:
                    sponlinks.append('''<a href="https://www.nmlegis.gov/Members/Legislator?SponCode=%s" title="%s" target="_blank">%s</a>
(<a href="%s" title="%s %s\'s committees and votes" target="_blank">about</a>)'''
                                     % (leg.sponcode, leg.get_summary(),
                                        leg.lastname,
                                        nmlegisbill.legislator_summary_url(leg),
                                        leg.short_salutation(), leg.lastname)
                                     )
                else:
                    sponlinks.append('%s <%s>' % (leg.lastname, leg.sponcode))

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
            print(self.billno, "NO STATUSTEXT!", file=sys.stderr)
            # outstr += "No action yet.\n"

        if self.location:
            # If it's on the House or Senate floor, highlight that:
            if self.location == 'House' or self.location == 'Senate':
                outstr += 'Location: ** %s Floor **\n' % self.location
            else:
                comm = Committee.query.filter_by(code=self.location).first()
                if comm:
                    outstr += 'Location: %s <%s>\n' % \
                        (comm.name, comm.get_link())
                else:
                    outstr += 'Location: %s\n' % self.location

            # The date to show is the most recent of last_action_date
            # or scheduled_date.
            last_action = self.last_action_date

            if self.scheduled_date:
                # postgres stores a dummy timezone to unaware datetimes,
                # ... and if you try to store a datetime with a local
                # timezone, it replaces it with the dummy without
                # adjusting the hour. Strip any bogus timezone here,
                # just in case.
                self.scheduled_date = \
                    self.scheduled_date.replace(tzinfo=None)
                if self.last_action_date:
                    self.last_action_date = \
                        self.last_action_date.replace(tzinfo=None)

                future = self.scheduled_in_future()
                sched_date = self.scheduled_date.date()
                today = datetime.now().date()

                # If the bill is scheduled in the future, bold it:
                if future:
                    if self.location == "House" or self.location == "Senate" \
                       or not self.scheduled_date.hour:
                        outstr += 'SCHEDULED: %s (check PDF schedules for time:\n    https://www.nmlegis.gov/Calendar/Session )' \
                            % (self.scheduled_date.strftime('%a %m/%d/%Y'))
                    else:
                        outstr += ' SCHEDULED: %s' \
                            % (self.scheduled_date.strftime('%a %m/%d/%Y %H:%M'))

                # if it's not considered future but still today,
                # highlight that:
                elif sched_date == today:
                    outstr += ' Was scheduled today, %s' \
                        % self.scheduled_date.strftime('%a %m/%d/%Y')

                # otherwise show the most recent of scheduled or last_action
                elif (self.last_action_date
                      and self.last_action_date > self.scheduled_date):
                    outstr += ' Last action: %s\n' % \
                        self.last_action_date.strftime('%a %m/%d/%Y')
                else:
                    outstr += ' (Last scheduled: %s)' \
                        % sched_date.strftime('%a %m/%d/%Y')
            outstr += '\n'

        else:
            outstr += 'Location: unknown\n'

        bill_info = nmlegisbill.bill_info(self.billno, self.year,
                                          LegSession.by_yearcode(self.year).id)
        # Currently, this is only used to detect tabled bills,
        # but eventually I hope it can be used for everything.

        if "tabled" in bill_info and bill_info["tabled"]:
            outstr += "TABLED "

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
            outstr += 'Sponsor: %s' % self.get_sponsor_links(html=False)

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

    # The legislator's code on the legislative website
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

    # home_phone is in Legislators.XLS but not on HTML pages.
    # It will probably be null.
    office_phone = db.Column(db.String(25))
    email = db.Column(db.String(50))
    office = db.Column(db.String(8))

    # Comma-separated list of commmittees this legislator chairs:
    chairships = db.Column(db.String(25))

    party = db.Column(db.String(10))
    county = db.Column(db.String(40))

    # Things we don't care about yet, but are available in the XLS;
    # district is now in Ed's legislators.json, but the others aren't.
    # district = db.Column(db.String(4))
    # lead_posi = db.Column(db.String(5))
    # start_year = db.Column(db.String(4))

    def __repr__(self):
        return '<Legislator %s: %s %s %s (%s, %s)>' % (
            self.title, self.sponcode,
            self.firstname, self.lastname,
            self.party, self.county
        )

    def get_url(self):
        return "https://www.nmlegis.gov/Members/Legislator?SponCode=%s" \
            % self.sponcode

    def get_summary(self):
        return "%s %s %s (%s, %s): %s" % (self.title,
                                         self.firstname, self.lastname,
                                         self.party, self.county,
                                         self.sponcode)

    def salutation(self):
        if self.sponcode[0] == 'S':
            return "Senator"
        return "Representative"

    def short_salutation(self):
        if self.sponcode[0] == 'S':
            return "Sen."
        return "Rep."

    @staticmethod
    def search(legstr):
        """Searching for legislators isn't always easy.
           You might have a sponcode, in which case it's trivial.
           Otherwise, you might have a last name, or a full name where
           it's not clear where the boundary is between the first and
           last name.
           Returns a Legislator object, or None.
        """
        # Is it a sponcode?
        if legstr.isupper():
            leg = Legislator.query.filter_by(sponcode=legstr).first()
            if leg:
                return leg
        # Is it a last name?
        legs = Legislator.query.filter_by(lastname=legstr).all()
        if len(legs) == 1:
            return legs[0]
        elif legs:
            print("Found multiple matches for %s!" % legstr,
                  ','.join([ str(l) for l in legs ]))
            return legs[0]

        if ' ' not in legstr:
            return None

        # Now the hard part: split off successive words and match against lastname
        spaceindex = -1
        while True:
            spaceindex = legstr[spaceindex+1:].find(' ')
            if spaceindex < 0:
                return None
            firstname = legstr[:spaceindex].lower()
            lastname = legstr[spaceindex+1:].lower()
            legs = Legislator.query.filter(Legislator.lastname.ilike(lastname),
                                           Legislator.firstname.ilike(firstname)).all()
            if not legs:
                continue
            if len(legs) == 1:
                return legs[0]
            print("Found multiple matches for lastname %s!" % lastname, legs,
                  file=sys.stderr)
            return legs[0]

        # Shouldn't ever get here, should have returned None from previous loop
        print("Internal error in Legislator.search", file=sys.stderr)
        return None

    @staticmethod
    def refresh_legislators_list():
        """Long-running, fetches XLS file from website,
           should not be called in user-facing code.
           Return True for success, else False.
        """
        leglist = nmlegisbill.get_legislator_list()
        if not leglist:
            print("Couldn't fetch legislators list", file=sys.stderr)
            return False

        for newleg in leglist:
            dbleg = Legislator.query.filter_by(
                sponcode=newleg['sponcode']).first()

            if not dbleg:
                dbleg = Legislator()

            for k in newleg:
                if hasattr(dbleg, k):
                    # XXX HACK: in 2024, leg id 56 has
                    # 'county': 'Colfax, Mora, Rio Arriba, San Miguel & Taos'
                    # which exceeds the 40 chars allocated for it
                    # so until we can do a db migration, truncate it:
                    if k == 'county' and len(newleg[k]) > 40:
                        newleg[k] = newleg[k][:40]
                    setattr(dbleg, k, newleg[k])
                # else:
                #     print("  ", newleg['sponcode'], "Skipping field", k,
                #           file=sys.stderr)

            db.session.add(dbleg)
            # Was getting obscure alembic errors,
            # psycopg2.DataError: value too long for type character varying(40)
            # which later went away; committing after each legislator
            # shouldn't be related or necessary, but I guess it doesn't hurt.
            db.session.commit()

        # db.session.commit()
        return True


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

    def update_from_parsed_page(self, newcom, yearcode=None):
        """Update a committee from the web, assuming the time-consuming
           web fetch has already been done.
        """
        if not yearcode:
            yearcode = LegSession.current_yearcode()

        self.code = newcom['code']
        self.name = newcom['name']

        if 'timestr' in newcom:
            self.mtg_time = newcom['timestr']
        else:
            self.mtg_time = ""

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
            for sched_pair in newcom['scheduled_bills']:
                # sched_pair is (billno, date_and_time)
                b = Bill.query.filter_by(billno=sched_pair[0],
                                         year=yearcode).first()
                if b:
                    b.location = self.code
                    b.scheduled_date = sched_pair[1]

                    # XXX Don't need to add(): that happens automatically
                    # when changing a field in an existing object.
                    db.session.add(b)
                    updated_bills.append(str(b))
                else:
                    # billno isn't in the database
                    not_updated_bills.append(sched_pair[0])

        self.last_check = datetime.now()

        db.session.add(self)
        db.session.commit()

        print("Updated bills", ', '.join(updated_bills))
        print("Skipped bills not in the db:", ', '.join(not_updated_bills))


    def refresh(self):
        """Refresh a committee from its web page.
        """
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
        return "LegSession(id=%d, '%s', %04d %s)" % (self.id, self.yearcode,
                                                     self.year, self.typename)

    @staticmethod
    def current_leg_session():
        """Return the latest legislative session.
        """
        # Used to use the session with the highest id, but that gave
        # randomly changing results. So instead, look at the year.
        latest_year = db.session.execute(db.select(
            func.max(LegSession.year))).scalar()
        year_sessions = LegSession.query.filter_by(year=latest_year).all()
        latest_session = year_sessions[0]
        for ys in year_sessions[1:]:
            if ys.yearcode > latest_session.yearcode:
                latest_session = ys

        return latest_session

    @staticmethod
    def current_yearcode():
        return LegSession.current_leg_session().yearcode

    @staticmethod
    def by_yearcode(yearcode):
        return LegSession.query.filter_by(yearcode=yearcode).first()

    @staticmethod
    def earlier_than(yearcode1, yearcode2):
        """Return True if yearcode1 is strictly earlier than yearcode2.
        """
        # With the extensions I know about, legigraphic order is correct.
        # But this might change, so be wary.
        return yearcode1 < yearcode2

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
        # from nnmlegisbill.

        for lsess in sessionsdict:
            # Is it in the database? Then we can stop: sessions
            # in Legislation_List are listed in reverse chronological,
            # so if we have this one we have everything after it.
            # Try/except is to handle sqlalchemy's changing API.
            try:
                if db.session.get(LegSession, lsess["id"]):
                    break
            except AttributeError:
                if LegSession.query.get(lsess["id"]):
                    print("Couldn't get session with id", lsess["id"],
                          file=sys.stderr)
                    break

            print("Making a new session with id", lsess["id"],
                  "year", lsess["year"], "yearcode", lsess["yearcode"],
                  "typename", lsess["typename"], file=sys.stderr)
            newsession = LegSession(id=lsess["id"],
                                    year = lsess["year"],
                                    yearcode = lsess["yearcode"],
                                    typename = lsess["typename"])
            db.session.add(newsession)

        db.session.commit()

    def sessionname(self):
        """Return the full session name, e.g. "2020 2nd Special"
           XXX This should probably move to nmlegisbill.
        """
        return "%4d %s" % (self.year, self.typename)

    def long_url_code(self):
        """Return the string that goes in the URL for analysis like FIR
           reports, which use a code like "20 Regular", "20 Special" or
           "20 Special2" (with space replaced with %20).
        """
        return nmlegisbill.yearcode_to_longURLcode(self.year)
