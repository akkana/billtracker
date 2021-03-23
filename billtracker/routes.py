from flask import render_template, flash, redirect, url_for, request, jsonify
from flask import session
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse

from billtracker import billtracker, db
from billtracker.forms import LoginForm, RegistrationForm, AddBillsForm, \
    UserSettingsForm, PasswordResetForm
from billtracker.models import User, Bill, Legislator, Committee, LegSession
from billtracker.bills import nmlegisbill, billutils, billrequests
from .emails import daily_user_email, send_email
from config import ADMINS

from datetime import datetime, timedelta, timezone, date
import dateutil.parser
import json
import requests
import random
import multiprocessing
import posixpath
import traceback
import shutil
import subprocess
import re
import sys, os


def set_session_by_request_values(values=None):
    """Set the session's yearcode and sessionname according to
       values passed into a requested page.
    """
    if values and "yearcode" in values:
        session["yearcode"] = values["yearcode"]
        session["sessionname"] = \
            LegSession.by_yearcode(session["yearcode"]).sessionname()
    elif "sessionname" not in session:
        leg_session = LegSession.current_leg_session()
        if not leg_session:
            print("Eek! No LegSessions defined. Fetching them...",
                  file=sys.stderr)
            LegSession.update_session_list()
            leg_session = LegSession.current_leg_session()
            if not leg_session:
                print("Double-eek! Couldn't fetch leg sessions",
                      file=sys.stderr)
                return
        session["yearcode"] = leg_session.yearcode
        session["sessionname"] = leg_session.sessionname()


#
# index.html can be called with a variety of sort views.
# Set sortby to one of (status, action_date, passed)
#
sortnames = {
    'status': 'Status',
    'action_date': 'Last action',
    'passed': 'Passed'
}

@billtracker.route('/')
@billtracker.route('/index')
@login_required
def index():
    values = request.values.to_dict()
    set_session_by_request_values(values)

    return render_template('index.html', title='Home',
                           sortby='status', sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


@billtracker.route('/status_bills')
@login_required
def statusbills():
    return redirect(url_for('index'))


@billtracker.route('/action_date_bills')
@login_required
def activebills():
    values = request.values.to_dict()
    set_session_by_request_values(values)

    return render_template('index.html', title='Home',
                           sortby='action_date', sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


@billtracker.route('/passed_bills')
@login_required
def passedbills():
    values = request.values.to_dict()
    set_session_by_request_values(values)

    return render_template('index.html', title='Home',
                           sortby='passed', sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


@billtracker.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html', title='Sign In', form=form)


@billtracker.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


# The mega tutorial called this /register,
# but flask seems to have a problem calling anything /register.
# As long as it's named something else, this works.
@billtracker.route('/newaccount', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        # Flask's unique=True doesn't work for optional (nullable) fields.
        # So we have to check for uniqueness manually here.
        if form.email.data:
            same_email = User.query.filter_by(email=form.email.data).first()
            if same_email:
                print("WARNING: Someone tried to register existing email",
                      form.email.data,
                      file=sys.stderr)
                flash("Sorry, that email address is already taken")
                return redirect(url_for("register"))

        print("Creating new user account", form.username.data,
              file=sys.stderr)
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)

        if user.email:
            try:
                print("Sending confirmation mail to", form.username.data)
                user.send_confirmation_mail()
                flash("Welcome to the NM Bill Tracker. A confirmation message has been mailed to %s."
                      % user.email)
            except Exception as e:
                print(e, file=sys.stderr)
                print("Couldn't send confirmation mail to", user.email,
                      file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                flash("You're registered! But something went wrong trying to send you a confirmation mail, so your email address won't work yet. Please contact an administrator. Sorry about that!")
        else:
            flash('Welcome to the NM Bill Tracker. Click Login to sign in.')

        db.session.add(user)
        db.session.commit()

        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)


@billtracker.route('/confirm_email/<auth>')
def confirm_email(auth):
    if auth == User.AUTH_CODE_CONFIRMED:
        flash("Bad auth code: Please contact an administrator")
        return redirect(url_for('user_settings'))

    user = User.query.filter_by(auth_code=auth).first()
    if not user:
        print("Couldn't find a user with auth code", auth, file=sys.stderr)
        flash("Sorry, I don't know that code. Please contact an administrator.")
        return redirect(url_for('user_settings'))

    # Correct code. Hooray!
    print("Confirming email address for user %s <%s>" % (user.username,
                                                         user.email),
          file=sys.stderr)
    user.confirm_email()
    flash("Your email address is now confirmed.")
    return redirect(url_for('login'))


@billtracker.route('/about')
def about():
    return render_template('about.html', title='About NMBillTracker')


@billtracker.route('/help')
def help():
    return render_template('help.html', title='Help for the NMBillTracker')


@billtracker.route('/links')
def links():
    return render_template('links.html', title='Links for NM Bill Tracking')


def make_new_bill(billno, yearcode):
    """Create a new Bill object, not previously in the database,
       by fetching and parsing its page.
       Don't actually add it to the database, just return the Bill object.
    """
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    b = nmlegisbill.parse_bill_page(billno, yearcode=yearcode,
                                    cache_locally=True)

    if b:
        bill = Bill()
        bill.set_from_parsed_page(b)
    else:
        bill = None

    return bill


@billtracker.route('/addbills', methods=['GET', 'POST'])
@login_required
def addbills():
    """The name is misleading. This is for either tracking or untracking:
       adding bills to a user's list, not to the general database.
    """
    user = User.query.filter_by(username=current_user.username).first()
    form = AddBillsForm()

    values = request.values.to_dict()
    set_session_by_request_values(values)

    if form.validate_on_submit():

        inputstr = form.billno.data.upper()

        # Be tolerant of input: e.g. "HB 1, SR03  ,  SB 222 "
        billno_strs = inputstr.split(",")

        bills_followed = []
        already_followed = []
        bills_err = []
        billnopat = re.compile("^[SH][JC]{0,1}[BMR][0-9]+$")
        for orig_billno in billno_strs:
            orig_billno = orig_billno.strip()

            # Remove internal spaces, e.g. "HB 22" should become "HB22"
            billno = orig_billno.replace(" ", "")

            # Remove leading zeros between letter and number,
            # e.g. "HB022" becomes "HB22":
            billno = re.sub(r"([BMR])0*", r"\1", billno)

            bill = Bill.query.filter_by(billno=billno,
                                        year=session["yearcode"]).first()
            if bill:
                # But is the user already following it?
                if bill in user.bills:
                    already_followed.append(billno)
                    continue
            else:
                try:
                    bill = make_new_bill(billno, session["yearcode"])
                    if bill:
                        db.session.add(bill)

                except RuntimeError as e:
                    print("Error making new bill for '%s':" % billno,
                          e, file=sys.stderr)
                    bill = None

                except Exception as e:
                    print(traceback.format_exc(), file=sys.stderr)
                    print("Couldn't add %s to the database:" % billno,
                          str(e), file=sys.stderr)
                    bill = None

            # Either way, bill should be set to a Bill object now.
            # Add it to the current user:
            if bill:
                user.bills.append(bill)
                db.session.add(user)
                db.session.commit()
                bills_followed.append(billno)
            else:
                if not billnopat.match(billno):
                    flash("'%s' doesn't look like a bill number" % orig_billno)
                    # Don't append to bills_err, flashing once is enough
                else:
                    flash("Couldn't find bill  %s" % billno)

        # Clear the form field
        form.billno.data = ""

        # Prepare the flash lines
        if bills_err:
            flash("Can't find " + ", ".join(bills_err))
        if already_followed:
            flash("You were already following " + ", ".join(already_followed))
        if bills_followed:
            flash("You are now following " + ", ".join(bills_followed))
    else:
        bill = None

    return render_template('addbills.html', title='Add More Bills',
                           bill_list=sorted(current_user.bills_by_yearcode(),
                                            key=Bill.bill_natural_key),
                           yearcode=session["yearcode"],
                           form=form, user=user)


#
# WTForms apparently doesn't have any way to allow adding checkboxes
# in a loop next to each entry; so this is an old-school form.
#
@billtracker.route('/track_untrack', methods=['GET', 'POST'])
@login_required
def track_untrack():
    """Called when the user marks bills for tracking or untracking
       via checkboxes, from either the addbills or allbills page.
    """
    if request.method == 'POST' or request.method == 'GET':
        # request contains form (for POST), args (for GET),
        # and values (combined); the first two are ImmutableMultiDict,
        # values is CombinedMultiDict.
        # I've found no way to iterate through
        # either ImmutableMultiDict or CombinedMultiDict;
        # to_dict() is the only way I've found of accessing the contents.

        track = []
        untrack = []

        values = request.values.to_dict()

        if 'returnpage' in values:
            returnpage = values['returnpage']
        else:
            returnpage = 'addbills'

        set_session_by_request_values(values)

        for billno in values:
            if values[billno] == 'on':
                # Untrack buttons may be u_BILLNO.YEAR or just BILLNO.YEAR;
                # track buttons will be f_BILLNO.YEAR.
                if billno.startswith('f_'):
                    track.append(billno[2:])
                elif billno.startswith('u_'):
                    untrack.append(billno[2:])
                else:
                    untrack.append(billno)

        # print("track:", track, file=sys.stderr)
        # print("untrack:", untrack, file=sys.stderr)

        if not track and not untrack:
            return redirect(url_for(returnpage))

        # Was querying the user here. Why? current_user is already set.
        # It's better not to do any database queries until we can batch
        # them all together.
        # user = User.query.filter_by(username=current_user.username).first()

        will_untrack = []
        not_tracking = []
        will_track = []
        already_tracking = []
        for billno in untrack:
            if current_user.tracking(billno, session["yearcode"]):
                will_untrack.append(billno)
            else:
                not_tracking.append(billno)
        for billno in track:
            if current_user.tracking(billno, session["yearcode"]):
                already_tracking.append(billno)
            else:
                will_track.append(billno)

        if already_tracking:
            flash("Already tracking %s" % ', '.join(already_tracking))

        if not_tracking:
            flash("Can't untrack %s; you weren't tracking them"
                  % ', '.join(not_tracking))

        if will_untrack:
            for b in current_user.bills_by_yearcode(session["yearcode"]):
                if b.billno in will_untrack:
                    current_user.bills.remove(b)
            flash("You are no longer tracking %s" % ', '.join(will_untrack))

        # The hard (and slow) part: make new bills as needed.
        # Can't really do this asynchronously (unless it's with AJAX)
        # since the user is waiting.
        # However, querying Bill.query.filter_by apparently holds
        # the database locked open, keeping anyone else from writing it
        # while make_new_bill fetches info.

        if will_track:
            # Figure out which bills will need to be fetched:
            # Bills the user wants to track that don't exist yet in the db:
            new_billnos = []
            # Bills that the user will start tracking:
            bills_to_track = []
            for billno in will_track:
                b = Bill.query.filter_by(billno=billno,
                                         year=session["yearcode"]).first()
                if b:
                    bills_to_track.append(b)
                else:
                    new_billnos.append(billno)

            # The session is open because of having done read queries.
            # Want to close it so it won't stay locked during the next part.
            # Does commit() close it? Not clear.
            db.session.commit()

            # Now, do the slow part: fetch the bills that need to be fetched.
            new_bills = []
            for billno in new_billnos:
                bill = make_new_bill(billno, session["yearcode"])
                if bill:
                    new_bills.append(bill)
                else:
                    print("WARNING: make_new_bill", billno, session["yearcode"],
                          "returned None!")
            flash("You are now tracking %s" % ', '.join(will_track))

            # Now add all the bills to track to the user's list
            # (hitting the database):
            for bill in bills_to_track:
                current_user.bills.append(bill)
            for bill in new_bills:
                db.session.add(bill)
                current_user.bills.append(bill)

        if will_track or will_untrack:
            # We changed something. Finish up and commit.
            db.session.add(current_user)
            db.session.commit()

    return redirect(url_for(returnpage))


# XXX Tried to allow specifying year (preferably optionally), but keep getting
# werkzeug.routing.BuildError: Could not build url for endpoint 'popular'. Did you forget to specify values ['year']?
# when visiting http://127.0.0.1:5000/popular/2020.
# @billtracker.route('/popular/<yearcode>')

@billtracker.route('/popular')
def popular():
    """Show all bills in the database for a given yearcode,
       and how many people are tracking each one.
    """
    set_session_by_request_values()
    yearcode = session["yearcode"]
    leg_session = LegSession.by_yearcode(session["yearcode"])
    bills = Bill.query.filter_by(year=yearcode).all()

    if current_user and not current_user.is_anonymous:
        user = User.query.filter_by(username=current_user.username).first()
        bills_seen = user.get_bills_seen(yearcode)
        bills_tracking = [ b.billno for b in user.bills if b.year == yearcode]
    else:
        user = None
        bills_seen = []
        bills_tracking = []

    # allbills.html expects a list of dictionaries with keys:
    # billno, title, url, contentsurl, user_tracking, num_tracking
    bill_list = []
    for bill in bills:
        num_tracking = bill.num_tracking()
        if num_tracking:
            if bill.amendlink:
                contentsurl = bill.amendlink
            else:
                contentsurl = bill.contentslink
            bill_list.append( { "billno": bill.billno,
                                "title": bill.title,
                                "url": bill.bill_url(),
                                "contentsurl": contentsurl,
                                "user_tracking":
                                    bill.billno in bills_tracking,
                                "num_tracking": num_tracking } )

    # Now sort by num_tracking, column 4:
    bill_list.sort(reverse=True, key=lambda l: l["num_tracking"])
    bill_lists = [ { 'thelist': bill_list,
                     'header': "",
                     'alt': "Nobody seems to be tracking anything" } ]

    verb = 'are' if yearcode >= LegSession.current_yearcode() else 'were'

    return render_template('allbills.html', user=current_user,
                           title="Bills People %s Tracking" % verb,
                           returnpage="popular",
                           yearcode=yearcode,
                           bill_lists=bill_lists)


@billtracker.route('/allbills')
def allbills():
    """Show all bills that have been filed in the given session,
       with titles and links,
       whether or not they're in our database or any user is tracking them.
       (Bills are only added to the database once someone tracks them.)
       New bills the user hasn't seen before are listed first.
    """
    set_session_by_request_values()
    leg_session = LegSession.by_yearcode(session["yearcode"])
    yearcode = session["yearcode"]
    if "sessionname" in session:
        sessionname = session["sessionname"]
    else:
        sessionbane = leg_session.sessionname()
        session["sessionname"] = sessionname

    # Do the slow part first, before any database accesses.
    # This can fail, e.g. if nmlegis isn't answering.
    try:
        allbills, titleschanged = nmlegisbill.all_bills(
            leg_session.id, yearcode, sessionname)
        # allbills is an OrderedDict,
        #   { billno: [title, url, contentslink, amendlink] }
        # titleschanged is a dict, { billno: "old title" }

    except Exception as e:
        print("Problem fetching all_bills", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        allbills = None

    if not allbills:
        flash("Problem fetching the list of all bills."
              "The legislative website my be overloaded.")
        return render_template('allbills.html',
                      title="NM Bill Tracker: Problem Fetching %s Bills"
                               % sessionname,
                               bill_lists=None)

    if current_user and not current_user.is_anonymous:
        user = User.query.filter_by(username=current_user.username).first()
        bills_seen = user.get_bills_seen(yearcode)
        bills_tracking = [ b.billno for b in user.bills if b.year == yearcode]
            # single query, don't query for each bill
    else:
        user = None
        bills_seen = []
        bills_tracking = []

    newbills = []
    oldbills = []

    from pprint import pprint
    # allbills.html expects a list of dictionaries with keys:
    # billno, title, url, contentsurl, user_tracking, num_tracking
    # [ [billno, title, link, fulltext_link, tracked_by_user ] ]
    for billno in allbills:
        # Used to query each bill here. That was nice because we could update
        # the bill's title and show a column for number of users tracking it;
        # but these queries turned out to be a huge performance bottleneck,
        # adding more than a second to page loading.
        if len(allbills[billno]) > 3 and allbills[billno][3]:
            contents = allbills[billno][3]
        else:
            contents = allbills[billno][2]
        args = { "billno": billno,
                 "title": allbills[billno][0],
                 "url": allbills[billno][1],
                 "contentsurl": contents,
                 "user_tracking": billno in bills_tracking
               }

        if user and (billno not in bills_seen or billno in titleschanged):
            newbills.append(args)
        else:
            oldbills.append(args)

    # Update user's bills seen, so they won't show up as new next time.
    if user:
        user.update_bills_seen(','.join(allbills.keys()), yearcode)

    bill_lists = [ { 'thelist': newbills,
                     'header': """<h2>Recently Filed Bills:</h2>
<p>
These are the new or changed bills since the last time you checked this page.
<br />
(Warning: that means that if you leave this page and load it again later,
or reload the page, these bills will no longer be listed as new.)""",
                     'alt': "Nothing new since you last looked."
                   },
                   { 'thelist': oldbills,
                     'header': "<h2>Older bills</h2>",
                     'alt': ""
                   } ]

    db.session.commit()

    return render_template('allbills.html', user=user,
                       title="NM Bill Tracker: All Bills in the %s Session" \
                                 % sessionname,
                           yearcode=yearcode,
                           bill_lists=bill_lists)


@billtracker.route("/config")
@login_required
def config():
    if current_user.email not in ADMINS:
        flash("Sorry, this page is only available to administrators.")
        return render_template('config.html', users=None)

    return render_template('config.html', users=User.query.all())


@billtracker.route("/changesession")
def changesession():
    if "yearcode" in session:
        cursession = LegSession.by_yearcode(session["yearcode"])
    else:
        cursession = LegSession.current_leg_session()

    sessionlist = []

    allsessions = LegSession.query.order_by(LegSession.id).all()
    for ls in allsessions:
        sessionname = ls.sessionname()
        if ls.id == cursession.id:
            sessionname += " (current)"
        sessionlist.insert(0, (ls.id, ls.yearcode, sessionname))

    return render_template("changesession.html", sessionlist=sessionlist)


@billtracker.route("/settings", methods=['GET', 'POST'])
@login_required
def user_settings():
    form = UserSettingsForm(obj=current_user)

    if form.validate_on_submit():
        newpasswd = form.password.data
        newpasswd2 = form.password2.data
        email = form.email.data
        updated = []

        if newpasswd and newpasswd2 and newpasswd == newpasswd2:
            current_user.set_password(newpasswd)
            updated.append("password")

        if email:
            # Make sure the new email address is unique:
            # This is duplicating a check that already happened in forms.py.
            u = User.query.filter_by(email=email).first()
            if u and u != current_user:
                flash("Sorry, that email address is not available")
                return render_template('settingshtml', form=form)

            if email != current_user.email:
                current_user.email = email
                updated.append("email")

        if updated:
            db.session.add(current_user)
            db.session.commit()
            flash("Updated " + ' and '.join(updated))

        if ((updated and "email" in updated) or
            (not current_user.email_confirmed())):
            print("Sending confirmation mail to %s <%s>, auth_code %s" \
                  % (current_user.username, current_user.email,
                     current_user.auth_code), file=sys.stderr)
            current_user.send_confirmation_mail()
            flash("Sent confirmation mail")

    return render_template('settings.html', form=form)


@billtracker.route("/password_reset", methods=['GET', 'POST'])
def password_reset():
    form = PasswordResetForm()

    if form.validate_on_submit():
        email = form.username.data
        user = User.query.filter_by(email=form.username.data).first()

        if user and user.email:
            # Generate a new password
            lc = 'abcdefghijklmnopqrstuvwxyz'
            uc = lc.upper()
            num = '0123456789'
            punct = '-.!@$%*'
            charset = lc+uc+num+punct
            newpasswd = ''
            passwdlen = 9
            for i in range(passwdlen):
                newpasswd += random.choice(charset)

            print("Sending password reset email to", user.email,
                  file=sys.stderr)
            send_email("NM Bill Tracker Password Reset",
                       "noreply@nmbilltracker.com", [ user.email ],
                       render_template("passwd_reset.txt",
                                       username=user.username,
                                       email=user.email,
                                       newpasswd=newpasswd))
            user.set_password(newpasswd)
            db.session.add(user)
            db.session.commit()

            flash("Mailed a new password to your email address")
        else:
            print("WARNING: unsuccessful attempt to reset password for email",
                  email, file=sys.stderr)
            flash("Sorry, no email address %s registered" % email)

    return render_template('passwd_reset.html', title='Password Reset',
                           form=form)


#
# API calls, not meant to be visited directly by users:
#


@billtracker.route("/api/appinfo/<key>")
def appinfo(key):
    """Display info about the app and the database.
    """
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    infostr = "<br>\nBillTracker at " + str(datetime.now())

    infostr += "<p>\nSQLALCHEMY_DATABASE_URI: " \
        + billtracker.config["SQLALCHEMY_DATABASE_URI"]
    infostr += '<br>\nDatabase: ' + str(db.session.get_bind())

    allusers = User.query.all()
    infostr += "<p>\n%d users registered." % len(allusers)

    # How active are the users?
    now = datetime.now(timezone.utc)
    yearcode = LegSession.current_yearcode()
    checked_in_last_day = 0
    never_checked = 0
    has_current_year_bills = 0
    totbills = 0
    spacer = '&nbsp;&nbsp;&nbsp;&nbsp;'
    for user in allusers:
        if user.last_check:
            print(user, "'s last check:", user.last_check, file=sys.stderr)
            if now - user.last_check.astimezone(timezone.utc) \
               < timedelta(days=1):
                checked_in_last_day += 1
        else:
            never_checked += 1

        totbills += len(user.bills)
        for bill in user.bills:
            if bill.year == yearcode:
                has_current_year_bills += 1
                break

    infostr += "<br>\n%swith bills from this session: %d" % (spacer,
                                                      has_current_year_bills)
    infostr += "<br>\n%schecked in past day: %d" % (spacer,
                                                    checked_in_last_day)
    infostr += "<br>\n%snever checked: %d" % (spacer, never_checked)

    infostr += "<br>\nAverage bills per user: %d" % (totbills / len(allusers))

    return "OK " + infostr


@billtracker.route("/api/all_daily_emails/<key>")
@billtracker.route("/api/all_daily_emails/<key>/<justpreview>")
def all_daily_emails(key, justpreview=False):
    """Send out daily emails to all users with an email address registered.
       A cron job will visit this URL once a day.
       To test the email system, pass any string as a second parameter.
    """
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    if justpreview:
        print("Preview of daily emails, not actually sending")

    recipients = []
    skipped = []

    # Get the current date. Bills' last action dates are just dates,
    # with the time set to 00:00:00. We'll consider a bill active if
    # its date is today or yesterday.
    today = date.today()

    for user in User.query.all():
        if not user.email:
            print("%s doesn't have an email address: not sending email"
                  % user.username, file=sys.stderr)
            continue

        if not user.email_confirmed():
            print("%s has an unconfirmed email address: not sending."
                  % user.username, file=sys.stderr)
            continue

        # Get this user's bills for the current yearcode.
        yearcode = LegSession.current_yearcode()

        bills = user.bills_by_yearcode(yearcode)

        if not bills:
            print("%s doesn't have any bills in this session: not emailing"
                  % user.username, file=sys.stderr)
            continue

        # slightly less than one day, in seconds
        oneday = 60*60*23.5
        sendmail = False
        for b in bills:
            # Bill last action dates are just dates, time is 00:00:00
            # so timezone is somewhat arbitrary. Use the local one.
            if b.last_action_date:
                lastaction = b.last_action_date.date()
                if today - lastaction <= timedelta(days=1):
                    sendmail = True
                    break

            if b.scheduled_in_future():
                sendmail = True
                break

        if sendmail:
            recipients.append('"%s" <%s>' % (user.username, user.email))
            if justpreview:
                print("Would send to", user.username, user.email,
                      file=sys.stderr)
            else:
                mailto(user.username, key)
        else:
            skipped.append('"%s" <%s>' % (user.username, user.email))
            print("Not emailing %s (%s): no active bills" % (user.username,
                                                             user.email),
                  file=sys.stderr)

    def userstring(userlist):
        if not userlist:
            return "<none>"
        return ', '.join(userlist)

    return "OK %s %s; Skipping %s" % \
        ("Testing, would email" if justpreview else "Emailing",
         userstring(recipients), userstring(skipped))


@billtracker.route('/api/mailto/<username>/<key>')
def mailto(username, key):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    user = User.query.filter_by(username=username).first()
    if not user:
        return "FAIL Couldn't get user for %s\n" % username

    if not user.email:
        return "FAIL %s doesn't have an email address registered.\n" % username

    print("** Sending email to %s (%s)" % (user.username, user.email),
          file=sys.stderr)
    try:
        daily_user_email(user)
    except Exception as e:
        print("Error, couldn't send email to %s (%s)" % (username, user.email),
              file=sys.stderr)
        print(e, file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return "FAIL couldn't send email to %s" % username

    # Update the user's last_check time and commit it to the database:
    user.last_check = datetime.now()
    db.session.add(user)
    db.session.commit()

    return "OK Mail sent to %s %s\n" % (username, user.email)


#
# Background bill updating:
#
# These are queries intended to be called from an update script,
# not from user action, to update bills and other information
# from their respective legislative website pages in the background.
#
# It would be nice to be able to spawn off a separate thread for
# updates, but there doesn't seem to be a way to do that in Flask with
# sqlite3 that's either documented or reliable (it tends to hit
# "database is locked" errors). But WSGI in Apache uses multiple
# threads and that sort of threading does work with Flask, so one of
# those threads will be used for refresh queries.
#

#
# Test with:
# requests.post('%s/api/refresh_one_bill' % baseurl,
#               { "BILLNO": billno, "YEARCODE": yearcode, "KEY": key }).text
#
# XXX PROBLEM: they've started putting bill text in filenames like
# SJR03.html, so now we'll have to look for bill text the same way
# as in refresh_legisdata.
@billtracker.route("/api/refresh_one_bill", methods=['POST'])
def refresh_one_bill():
    """Long-running query: fetch the page for a bill and update it in the db.
       Send BILLNO, YEARCODE and the app KEY in POST data.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_one_bill: bad key %s" % key, file=sys.stderr)
        return "FAIL Bad key\n"
    billno = request.values.get('BILLNO')

    yearcode = request.values.get('YEARCODE')
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    b = nmlegisbill.parse_bill_page(billno, yearcode, cache_locally=True)
    if not b:
        print("FAIL refresh_one_bill: Couldn't fetch %s bill page" % billno,
              file=sys.stderr)
        return "FAIL Couldn't fetch %s bill page" % billno

    bill = Bill.query.filter_by(billno=billno, year=yearcode).first()
    if not bill:
        bill = Bill()
    bill.set_from_parsed_page(b)

    db.session.add(bill)
    db.session.commit()

    newbill = Bill.query.filter_by(billno=billno, year=yearcode).first()

    return "OK Updated %s" % billno


@billtracker.route("/api/refresh_session_list", methods=['POST'])
def refresh_session_list():
    """Fetch Legislation_List (the same file that's used for allbills)
       and check the menu of sessions to see if there's a new one.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_session_list: bad key %s" % key, file=sys.stderr)
        print(billtracker.config["SECRET_KEY"], file=sys.stderr)
        return "FAIL Bad key\n"

    LegSession.update_session_list()
    return "OK Refreshed list of legislative sessions"


@billtracker.route("/api/bills_by_update_date", methods=['GET'])
def bills_by_update_date():
    """Return a list of bills in the current legislative yearcode,
       sorted by how recently they've been updated, oldest first.
       No key required.
    """
    yearcode = request.values.get('yearcode')
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    bill_list = Bill.query.filter_by(year=yearcode) \
                          .order_by(Bill.update_date).all()
    return ','.join([ bill.billno for bill in bill_list ])


# Update LESC, FIR, amendments
# (relatively long-running, see comment above re threads).
#
# Test with:
# posturl = '%s/api/refresh_legisdata' % baseurl
# lescdata = { "TARGET": "LESClink",
#              "URL": "ftp://www.nmlegis.gov/LESCAnalysis",
#              "YEARCODE": "19",    # optional
#              "KEY"='...' }
# firdata = { "TARGET": "FIRlink", "URL": "ftp://www.nmlegis.gov/firs",
#             "YEARCODE": "19",    # optional
#             "KEY"='...' }
# amenddata = { "TARGET": "amendlink",
#               "URL": "ftp://www.nmlegis.gov/Amendments_In_Context",
#               "YEARCODE": "19",    # optional
#               "KEY"='...' }
# requests.post(posturl, xyzdata).text
@billtracker.route("/api/refresh_legisdata", methods=['POST'])
def refresh_legisdata():
    """Fetch a specific file from the legislative website in a separate thread,
       which will eventually update a specific field in the bills database.
       This is used for refreshing things like FIR, LESC, amendment links.
       POST data required:
         TARGET is the field to be changed (e.g. FIRlink);
         URL is the ftp index for that link, e.g. ftp://www.nmlegis.gov/firs/
         KEY is the app key.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    yearcode = request.values.get('YEARCODE')
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    target = request.values.get('TARGET')

    url = request.values.get('URL')
    if not url:
        url = "https://www.nmlegis.gov/Sessions/%s/" \
            % nmlegisbill.yearcode_to_longURLcode(yearcode)
        if target == "LESClink":
            url += "LESCAnalysis"
        elif target == "FIRlink":
            url += "firs"
        elif target == "amendlink":
            url += "Amendments_In_Context"
        else:
            errstr = \
                "refresh_legisdata: unknown target %s and no URL specified" \
                % target
            print(errstr, file=sys.stderr)
            return "FAIL " + errstr

    print("refresh_legisdata %s from %s" % (target, url), file=sys.stderr)

    try:
        # XXX Warning: the ftp stuff hasn't been tested recently.
        if url.startswith("ftp:"):
            index = billrequests.ftp_url_index(url)
        else:
            index = billrequests.get_http_dirlist(url)
    except Exception as e:
        print("Couldn't fetch", url, file=sys.stderr)
        print(e, file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return "FAIL Couldn't fetch %s" % url

    # Slow part is done. Now it's okay to access the database.

    # filenames are e.g. HB000032.PDF with a random number of zeros.
    # Remove all zeros -- but not in the middle of a number, like 103.
    billno_pat = re.compile("([A-Z]*)(0*)([1-9][0-9]*)")

    changes = []
    not_in_db = []
    # index is a list of dicts with keys name, url, size, Last Modified
    for filedic in index:
        base, ext = os.path.splitext(filedic["name"])

        try:
            # Remove those extra zeros
            match = billno_pat.match(base)
            billno = match.group(1) + match.group(3)
        except:
            billno = base
            print("billpat didn't patch, base is", base, file=sys.stderr)

        bill = Bill.query.filter_by(billno=billno, year=yearcode).first()
        if bill:
            setattr(bill, target, filedic["url"])
            db.session.add(bill)
            changes.append(billno)
        else:
            not_in_db.append(billno)

    if not changes:
        return "OK but no bills updated"

    db.session.commit()
    return "OK<br>\nUpdated %s for %s<br>\nNot in database: %s" \
        % (target, ','.join(changes), ','.join(not_in_db))


@billtracker.route("/api/refresh_legislators", methods=['POST'])
def refresh_legislators():
    """POST data is only for specifying KEY.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    Legislator.refresh_legislators_list()


@billtracker.route("/api/all_committees")
def list_committees():
    """List all committee codes in the db, in no particular order.
       No key required.
    """
    all_committees = Committee.query.all()
    if not all_committees:
        print("No committees were set! Should refresh all of them.",
              file=sys.stderr)
        # refresh_all_committees(billtracker.config["SECRET_KEY"])

    all_committees = Committee.query.all()
    return ','.join([ c.code for c in all_committees ])


@billtracker.route("/api/refresh_all_committees/<key>")
def refresh_all_committees(key):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"
    print("Refreshing all committees", file=sys.stderr)

    set_session_by_request_values()
    yearcode = session["yearcode"]

    # First update the legislators list:
    Legislator.refresh_legislators_list()

    # Get the list of all committees that are locations for bills.
    # There's no pressing need to refresh committees not in that list.
    # Some bill locations aren't committees, e.g. "chaptered" or "Senate".
    comm_locs = set()
    for bill in Bill.query.filter_by(year=yearcode).all():
        if bill.location and \
           not nmlegisbill.is_special_location(bill.location):
            comm_locs.add(bill.location)

    # House and Senate are special locations: don't skip them.
    comm_locs.add("House")
    comm_locs.add("Senate")
    print("api/refresh_all_committees: will refresh", ' '.join(comm_locs),
          file=sys.stderr)

    refreshed = []
    inactive = []
    for code in comm_locs:
        ret = refresh_one_committee(code)
        if ret.startswith("FAIL"):
            inactive.append(code)
        else:
            refreshed.append(code)
        print(ret, file=sys.stderr)

    if refreshed:
        return "OK\n<br>Refreshed: " + ",".join(refreshed) \
            + "\n<br>Inactive: " + ",".join(inactive)


def refresh_one_committee(comcode):
    print("refresh_one_committee: Updating committee", comcode,
          file=sys.stderr)
    newcom = nmlegisbill.expand_committee(comcode)
    if not newcom:
        print("Couldn't expand committee %s" % comcode, file=sys.stderr)
        return "FAIL Couldn't expand committee %s" % comcode

    com = Committee.query.filter_by(code=comcode).first()
    if not com:
        com = Committee()
        com.code = comcode

    com.update_from_parsed_page(newcom)

    db.session.add(com)
    db.session.commit()

    return "OK Updated committee %s" % comcode


@billtracker.route("/api/refresh_committee/<comcode>/<key>")
def refresh_committee(comcode, key):
    """Long-running API: update a committee from its website.
       POST data includes COMCODE and KEY.
    """
    # key = request.values.get('KEY')
    # if key != billtracker.config["SECRET_KEY"]:
    #     return "FAIL Bad key\n"

    # comcode = request.values.get('COMCODE')
    # if not comcode:
    #     return "FAIL No COMCODE\n"

    return refresh_one_committee(comcode)


@billtracker.route("/api/db_backup", methods=['GET', 'POST'])
def db_backup():
    """Make a backup copy of the database.
       POST data is only for KEY.
    """

    values = request.values.to_dict()

    try:
        key = values['KEY']
        if key != billtracker.config["SECRET_KEY"]:
            return "FAIL Bad key\n"
    except KeyError:
        return "FAIL No key"

    db_uri = billtracker.config['SQLALCHEMY_DATABASE_URI']
    print("db URI:", db_uri, file=sys.stderr)

    now = datetime.now()
    backupdir = os.path.join(billrequests.CACHEDIR, "db")

    db_orig = db_uri[9:]

    if not os.path.exists(backupdir):
        try:
            os.mkdir(backupdir)
        except Exception as e:
            return "FAIL Couldn't create backupdir %s: %s" % (backupdir, str(e))

    if not os.path.exists(backupdir):
        return "FAIL No backupdir %s" % (backupdir)

    if db_uri.startswith('sqlite://'):
        db_new = os.path.join(backupdir,
                              now.strftime('billtracker-%Y-%m-%d_%H:%M.db'))
        shutil.copyfile(db_orig, db_new)

    elif db_uri.startswith('postgresql://'):
        db_new = os.path.join(backupdir,
            now.strftime('billtracker-%Y-%m-%d_%H:%M.psql'))
        # pg_dump dbname > dbname-backup.pg
        with open(db_new, 'w') as fp:
            subprocess.call(["pg_dump", "nmbilltracker"], stdout=fp)
            print("Backed up to", db_new, file=sys.stderr)

    else:
        return "FAIL db URI doesn't start with sqlite:// or postgresql://"

    return "OK Backed up database to '%s'" % (db_new)


def find_dups():
    """Return a list of all bills that have duplicate entries in the db:
       multiple bills for the same billno and year.
       Return a list of lists of bills.
       Return only the master bill for each billno.
    """

    # A list of all bills that have duplicates, same billno and year.
    dup_bill_lists = []
    bill_ids_seen = set()

    bills = Bill.query.all()
    for bill in bills:
        # Already seen because it was a dup of something else?
        if bill.id in bill_ids_seen:
            continue

        bill_ids_seen.add(bill.id)

        bills_with_this_no = Bill.query.filter_by(billno=bill.billno,
                                                  year=bill.year) \
                                       .order_by(Bill.id).all()
        if len(bills_with_this_no) == 1:
            continue

        # There are multiple bills with this billno.
        print(len(bills_with_this_no), "bills called", bill.billno, bill.year,
              file=sys.stderr)

        dup_bill_lists.append(bills_with_this_no)

        for dupbill in bills_with_this_no:
            bill_ids_seen.add(dupbill.id)

    return dup_bill_lists


@billtracker.route('/api/showdups/<key>')
def show_dups(key):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    dup_bill_lists = find_dups()

    if not dup_bill_lists:
        print("No duplicate bills in database, whew")
        return "OK"

    print("duplicate bills:", dup_bill_lists, file=sys.stderr)

    retstr = "OK"
    for dupbills in dup_bill_lists:
        retstr += "<br>\n%s: " % (str(dupbills[0]))
        for b in dupbills:
            retstr += "<br>&nbsp;&nbsp;id %d '%s' (%d tracking) " \
                % (b.id, b.title, b.num_tracking())

    return retstr


# Clean out duplicates.
# This shouldn't be needed, but somehow, duplicates appear.
@billtracker.route('/api/cleandups/<key>')
def clean_dups(key):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    return "FAIL Sorry, clean_dups currently disabled as unsafe"

    masterbills = find_dups()

    if not masterbills:
        print("No duplicate bills in database, whew")
        return "OK"

    print("masterbills:", masterbills, file=sys.stderr)

    # Now make a separate loop, so we're not changing the list of all bills
    # while looping over the list of all bills.
    for masterbill in masterbills:
        print("%s, master is id %d" % (masterbill.billno, masterbill.id),
              file=sys.stderr)

        bills_with_this_no = Bill.query.filter_by(billno=masterbill.billno).all()
        print("  %d bills with this no: %s" % (len(bills_with_this_no),
                                       [b.id for b in bills_with_this_no]),
              file=sys.stderr)

        for i, b in enumerate(bills_with_this_no):
            if b.id == masterbill.id:
                continue
            users = b.users_tracking()
            if users:
                print("  Moving id %d's users over to id %d: %s"
                      % (bills_with_this_no[i].id,
                         masterbill.id,
                         [u.username for u in users]), file=sys.stderr)
                for u in users:
                    if b not in u.bills:
                        print("Eek, id %d thinks %s is tracking but %s doesn't think so" % (b.id, u.username), file=sys.stderr)
                        continue
                    if masterbill not in u.bills:
                        u.bills.append(masterbill)
                        print("    moved %s" % u.username, file=sys.stderr)
                    else:
                        print("    %s was already tracking %d" % (u.username,
                                                                masterbill.id),
                              file=sys.stderr)
                    u.bills.remove(b)
                    db.session.add(u)
            else:
                print("  id %d had no users" % b.i, file=sys.stderr)

            print("  Deleting bill id %d" % b.id, file=sys.stderr)
            db.session.delete(b)

        db.session.add(masterbill)

    if masterbills:
        db.session.commit()
    return "OK"
