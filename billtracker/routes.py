from flask import render_template, flash, redirect, url_for, request, jsonify
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse

from billtracker import billtracker, db
from billtracker.forms import LoginForm, RegistrationForm, AddBillsForm, \
    UserSettingsForm, PasswordResetForm
from billtracker.models import User, Bill, Legislator, Committee
from billtracker.bills import nmlegisbill, billutils
from .emails import daily_user_email, send_email
from config import ADMINS

from datetime import datetime, timedelta
import dateutil.parser
import json
import requests
# from collections import OrderedDict
import random
import multiprocessing
import posixpath
import traceback
import shutil
import subprocess
import sys, os


@billtracker.route('/')
@billtracker.route('/index')
@login_required
def index():
    return render_template('index.html', title='Home', sortby='status')


@billtracker.route('/statusbills')
@login_required
def statusbills():
    return render_template('index.html', title='Home', sortby='status')


@billtracker.route('/activebills')
@login_required
def activebills():
    return render_template('index.html', title='Home', sortby='action_date')


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
    return redirect(url_for('index'))


# The mega tutorial called this /register,
# but flask seems to have a problem calling anything /register.
# As long as it's named something else, this works.
@billtracker.route('/newaccount', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)

        if user.email:
            try:
                user.send_confirmation_mail()
                flash("Welcome to the NM Bill Tracker. A confirmation message has been mailed to %s."
                      % user.email)
            except:
                flash("You're registered! But something went wrong trying to send you a confirmation mail, so your email address won't work yet. Please contact an administrator. Sorry about that!")
        else:
            flash('Welcome to the NM Bill Tracker. Click Login to sign in.')

        db.session.add(user)
        db.session.commit()

        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)


@billtracker.route('/confirm_email/<auth>')
def confirm_email(auth):
    user = User.query.filter_by(auth_code=auth).first()
    if not user:
        flash("Sorry, I don't know that code. Please contact an administrator.")
        return redirect(url_for('user_settings'))

    # Correct code. Hooray!
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


def make_new_bill(billno, leg_year=None):
    '''Create a new Bill object, not previously in the database,
       by fetching and parsing its page.
       Don't actually add it to the database, just return the Bill object.
    '''
    if not leg_year:
        leg_year = billutils.current_leg_year()

    b = nmlegisbill.parse_bill_page(billno, leg_year,
                                    cache_locally=True)

    if b:
        bill = Bill()
        bill.set_from_parsed_page(b)
    else:
        bill = None
        flash("Couldn't fetch information for %s" % billno)

    return bill


@billtracker.route('/addbills', methods=['GET', 'POST'])
@login_required
def addbills():
    '''Despite the name, this is for either tracking or untracking.
    '''
    user = User.query.filter_by(username=current_user.username).first()
    form = AddBillsForm()

    values = request.values.to_dict()

    if form.validate_on_submit():
        billno = form.billno.data
        bill = Bill.query.filter_by(billno=billno).first()
        if bill:
            # But is the user already following it?
            if bill in user.bills:
                flash("You're already following " + billno)
                return redirect(url_for('addbills'))
        else:
            try:
                bill = make_new_bill(billno)
                db.session.add(bill)

            except RuntimeError as e:
                flash(str(e))
                return render_template('addbills.html', title='Add More Bills',
                                       form=form, user=user)
            except Exception as e:
                flash("Couldn't add %s to the database: %s" % (billno, str(e)))
                print("Couldn't add %s to the database: %s" % (billno, str(e)),
                      file=sys.stderr)

        # Either way, bill should be set to a Bill object now.
        # Add it to the current user:
        if bill:
            user.bills.append(bill)
            db.session.add(user)
            db.session.commit()

            flash("You're now tracking %s: %s" % (bill.billno, bill.title))

        # Clear the form field
        form.billno.data = ""
    else:
        bill = None

    return render_template('addbills.html', title='Add More Bills',
                           form=form, user=user)


#
# WTForms apparently doesn't have any way to allow adding checkboxes
# in a loop next to each entry; so this is an old-school form.
#
@billtracker.route('/track_untrack', methods=['GET', 'POST'])
@login_required
def track_untrack():
    '''Called when the user marks bills for tracking or untracking
       via checkboxes, from either the addbills or allbills page.
    '''
    print("track_untrack()")
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

        if 'leg_year' in values:
            leg_year = values['leg_year']
        else:
            leg_year = billutils.current_leg_year()

        yearstr = billutils.year_to_2digit(leg_year)

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

        print("track:", track)
        print("untrack:", untrack)

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
            if current_user.tracking(billno, yearstr):
                will_untrack.append(billno)
            else:
                not_tracking.append(billno)
        for billno in track:
            if current_user.tracking(billno, yearstr):
                already_tracking.append(billno)
            else:
                will_track.append(billno)

        if already_tracking:
            flash("Already tracking %s" % ', '.join(already_tracking))

        if not_tracking:
            flash("Can't untrack %s; you weren't tracking them"
                  % ', '.join(not_tracking))

        if will_untrack:
            for b in current_user.bills_by_year(yearstr):
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
                b = db.session.query(Bill).filter(Bill.billno == billno).first()
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
                print("Needed to make a new bill for", billno, yearstr,
                      "in track_untrack")
                bill = make_new_bill(billno, leg_year)
                new_bills.append(bill)
            flash("You are now tracking %s" % ', '.join(will_track))

            # Now add all the bills to track to the user's list
            # (hitting the database):
            for bill in bills_to_track:
                current_user.bills.append(bill)
            for bill in new_bills:
                print("Adding new bill", bill, "to the db")
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
# @billtracker.route('/popular/<year>')

@billtracker.route('/popular')
@login_required
def popular():
    '''Show all bills in the database for a given year,
       and how many people are tracking each one.
       This requires login, only because it seems rude to show information
       about our users to someone who can't be bothered to register.
    '''
    year = billutils.current_leg_year()
    yearstr = billutils.year_to_2digit(year)
    bills = Bill.query.all()
    # allbills.html expects a list of
    # [ [billno, title, link, fulltext_link, num_tracking ] ]
    bill_list = []
    for bill in bills:
        if bill.year != yearstr:
            continue
        num_tracking = bill.num_tracking()
        if num_tracking:
            bill_list.append( [ bill.billno, bill.title,
                                bill.bill_url(), bill.contentslink,
                                num_tracking ] )

    # Now sort by num_tracking, column 4:
    bill_list.sort(reverse=True, key=lambda l: l[4])
    bill_lists = [ { 'thelist': bill_list,
                     'header': "",
                     'alt': "Nobody seems to be tracking anything" } ]

    verb = 'are' if year >= billutils.current_leg_year() else 'were'

    return render_template('allbills.html', user=current_user,
                           title="%s Bills People %s Tracking" % (year, verb),
                           leg_year=year,
                           returnpage="popular",
                           bill_lists=bill_lists)


@billtracker.route('/allbills')
def allbills():
    '''Show all bills that have been filed, with titles and links,
       whether or not they're in our database or any user is tracking them.
       New bills the user hasn't seen before are listed first.
       By default, though, only show the current session.
    '''
    leg_year = billutils.current_leg_year()

    # Do the slow part first, before any database accesses:
    allbills = nmlegisbill.all_bills(leg_year)
    # This is an OrderedDict, { billno: [title, url] }

    bills_seen = []
    if current_user and not current_user.is_anonymous:
        user = User.query.filter_by(username=current_user.username).first()

        if user.bills_seen:
            bills_seen = user.bills_seen.split(',')
    else:
        user = None

    newbills = []
    oldbills = []
    if not allbills:
        flash("Problem fetching the list of all bills")
        allbills = []

    # allbills.html expects a list of
    # [ [billno, title, link, fulltext_link, num_tracking ] ]
    for billno in allbills:
        contentsurls = nmlegisbill.contents_url_for_billno(billno)
        if contentsurls:
            contents = contentsurls[0]
        else:
            contents = ''
        args = [ billno, allbills[billno][0], allbills[billno][1],
                 contents, Bill.num_tracking_billno(billno, leg_year) ]

        if user and billno not in bills_seen:
            newbills.append(args)
        else:
            oldbills.append(args)

    # Update user
    if user:
        user.bills_seen = ','.join(allbills.keys())
        db.session.add(user)
        db.session.commit()

    bill_lists = [ { 'thelist': newbills,
                     'header': """<h2>Recently Filed Bills:</h2>
<p>
These are the bills filed since the last time you checked this page.
<br />
(Warning: that means that if you leave this page and come back,
or reload the page, these bills will no longer be there!
So check them now.)""",
                     'alt': "Nothing new since you last looked."
                   },
                   { 'thelist': oldbills,
                     'header': "<h2>Older bills</h2>",
                     'alt': ""
                   } ]

    return render_template('allbills.html', user=user,
                           title="NM Bill Tracker: All %d Bills" \
                                 % billutils.current_leg_year(),
                           leg_year=leg_year,
                           bill_lists=bill_lists)


@billtracker.route("/config")
@login_required
def config():
    if current_user.email not in ADMINS:
        flash("Sorry, this page is only available to administrators.")
        return render_template('config.html', users=None)

    return render_template('config.html', users=User.query.all())


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
            print("Sending confirmation mail to %s, I hope"
                  % current_user.email)
            current_user.send_confirmation_mail()
            flash("Sent confirmation mail")

    return render_template('settings.html', form=form)


@billtracker.route("/password_reset", methods=['GET', 'POST'])
def password_reset():
    form = PasswordResetForm()

    if form.validate_on_submit():
        username = form.username.data
        user = User.query.filter_by(username=form.username.data).first()
        if not user:
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

            print("Sending email to", user.email)
            send_email("NM Bill Tracker Password Reset",
                       "noreply@nmbilltracker.com", [ user.email ],
                       render_template("passwd_reset.txt", recipient=username,
                                       newpasswd=newpasswd))
            user.set_password(newpasswd)
            db.session.add(user)
            db.session.commit()

            flash("Mailed a new password to your email address")
        else:
            flash("Sorry, no user %s with an email address" % username)

    return render_template('passwd_reset.html', title='Password Reset',
                           form=form)


#
# API calls, not meant to be visited directly by users:
#


@billtracker.route("/api/appinfo/<key>")
def appinfo(key):
    '''Send out daily emails to all users with an email address registered.
       A cron job will visit this URL once a day.
    '''
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    infostr = "BillTracker"
    infostr += '\nDatabase: ' + str(db.session.get_bind())

    return "OK\n" + infostr


@billtracker.route("/api/all_daily_emails/<key>")
def all_daily_emails(key):
    '''Send out daily emails to all users with an email address registered.
       A cron job will visit this URL once a day.
    '''
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    for user in User.query.all():
        if not user.email:
            print("%s doesn't have an email address: not sending email"
                  % user.username)
            continue

        if not user.email_confirmed():
            print("%s has an unconfirmed email address: not sending."
                  % user.username)
            continue

        if not user.bills:
            print("%s doesn't have any bills registered: not sending email"
                  % user.username)
            continue

        mailto(user.username, key)

    return "OK\n"


@billtracker.route('/api/mailto/<username>/<key>')
def mailto(username, key):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    user = User.query.filter_by(username=username).first()
    if not user:
        return "FAIL Couldn't get user for %s\n" % username

    if not user.email:
        return "FAIL %s doesn't have an email address registered.\n" % username

    print("Sending email to", user.username)
    try:
        daily_user_email(user)
    except Exception as e:
        print("Error, couldn't send email to %s" % username, file=sys.stderr)
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
#               { "BILLNO": billno, "YEAR": year, "KEY": key }).text
#
@billtracker.route("/api/refresh_one_bill", methods=['POST'])
def refresh_one_bill():
    '''Long-running query: fetch the page for a bill and update it in the db.
       Send BILLNO, YEAR and the app KEY in POST data.
    '''
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_one_bill: bad key %s" % key)
        return "FAIL Bad key\n"
    billno = request.values.get('BILLNO')

    year = request.values.get('YEAR')
    if not year:
        year = datetime.now().year

    b = nmlegisbill.parse_bill_page(billno, year, cache_locally=True)
    if not b:
        print("FAIL refresh_one_bill: Couldn't fetch %s bill page" % billno)
        return "FAIL Couldn't fetch %s bill page" % billno

    bill = Bill.query.filter_by(billno=billno).first()
    if not bill:
        bill = Bill()
    bill.set_from_parsed_page(b)

    db.session.add(bill)
    print("Refreshed %s from parsed page; committing" % billno)
    db.session.commit()

    return "OK Updated %s" % billno


@billtracker.route("/api/bills_by_update_date")
def bills_by_update_date():
    '''Return a list of bills sorted by how recently they've been updated,
       oldest first. No key required.
    '''
    bill_list = Bill.query.order_by(Bill.update_date).all()
    return ','.join([ bill.billno for bill in bill_list ])


# Update LESC, FIR, amendments
# (relatively long-running, see comment above re threads).
#
# Test with:
# posturl = '%s/api/refresh_legisdata' % baseurl
# lescdata = { "TARGET": "LESClink",
#              "URL": "ftp://www.nmlegis.gov/LESCAnalysis",
#              "KEY"='...' }
# firdata = { "TARGET": "FIRlink", "URL": "ftp://www.nmlegis.gov/firs",
#             "KEY"='...' }
# amenddata = { "TARGET": "amendlink",
#               "URL": "ftp://www.nmlegis.gov/Amendments_In_Context",
#               "KEY"='...' }
# requests.post(posturl, xyzdata).text
@billtracker.route("/api/refresh_legisdata", methods=['POST'])
def refresh_legisdata():
    '''Fetch a specific file from the legislative website in a separate thread,
       which will eventually update a specific field in the bills database.
       This is used for refreshing things like FIR, LESC, amendment links.
       POST data required:
         TARGET is the field to be changed (e.g. FIRlink);
         URL is the ftp index for that link, e.g. ftp://www.nmlegis.gov/firs/
         KEY is the app key.
    '''
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    url = request.values.get('URL')
    target = request.values.get('TARGET')
    print("refresh_legisdata %s from %s" % (target, url))

    try:
        index = billutils.ftp_url_index(url)
    except:
        return "FAIL Couldn't fetch %s" % url

    print("Fetched %s" % url)

    # Slow part is done. Now it's okay to access the database.

    # Get all bills that might need updating:
    # bills = Bill.query.filter(Bill.billno.in_(billnos)).all()

    changes = []
    for l in index:
        try:
            filename, date, size = l
        except:
            print("Can't parse ftp line: %s" % l)
            continue

        base, ext = os.path.splitext(filename)

        # filenames are e.g. HB0032.PDF. Remove zeros.
        billno = base.replace('0', '')
        bill = Bill.query.filter_by(billno=billno).first()
        if bill:
            setattr(bill, target, posixpath.join(url, filename))
            db.session.add(bill)
            changes.append(billno)
        # else:
        #     print("%s isn't in the database" % billno)

    if not changes:
        return "OK but no bills updated"

    db.session.commit()
    return "OK Updated " + ','.join(changes)


@billtracker.route("/api/refresh_legislators", methods=['POST'])
def refresh_legislators():
    '''POST data is only for specifying KEY.
    '''
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    Legislator.refresh_legislators_list()


@billtracker.route("/api/all_committees")
def list_committees():
    '''List all committee codes in the db, in no particular order.
       No key required.
    '''
    return ','.join([ c.code for c in Committee.query.all() ])


@billtracker.route("/api/refresh_committee", methods=['POST'])
def refresh_committee():
    '''Long-running API: update a committee from its website.
       POST data includes COMCODE and KEY.
    '''
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    comcode = request.values.get('COMCODE')
    if not comcode:
        return "FAIL No COMCODE\n"

    print("Updating committee", comcode, "from the web")
    newcom = nmlegisbill.expand_committee(comcode)
    if not newcom:
        return "FAIL Couldn't expand committee %s" % comcode

    com = Committee.query.filter_by(code=comcode).first()
    if not com:
        com = Committee()
        com.code = comcode

    com.update_from_parsed_page(newcom)
    db.session.commit()

    return "OK Updated committee %s" % comcode


@billtracker.route("/api/db_backup", methods=['GET', 'POST'])
def db_backup():
    '''Make a backup copy of the database.
       POST data is only for KEY.
    '''

    values = request.values.to_dict()
    print("request values:", values)
    try:
        key = values['KEY']
        if key != billtracker.config["SECRET_KEY"]:
            return "FAIL Bad key\n"
    except KeyError:
        return "FAIL No key"

    db_uri = billtracker.config['SQLALCHEMY_DATABASE_URI']
    print("db URI:", db_uri)

    now = datetime.now()
    backupdir = os.path.join(nmlegisbill.cachedir, "db")

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
            print("Backed up to", db_new)

    else:
        return "FAIL db URI doesn't start with sqlite:// or postgresql://"

    return "OK Backed up database to '%s'" % (db_new)


def find_dups():
    '''Return a list of all bills that have duplicate entries in the db:
       multiple bills for the same billno.
       Return only the master bill for each billno.
    '''

    # A list of all bills that have duplicates
    masterbills = []
    bill_ids_seen = set()

    bills = Bill.query.all()
    for bill in bills:
        # Already seen because it was a dup of something else?
        if bill.id in bill_ids_seen:
            continue

        bill_ids_seen.add(bill.id)

        bills_with_this_no = Bill.query.filter_by(billno=bill.billno).all()
        if len(bills_with_this_no) == 1:
            continue

        # There are multiple bills with this billno.
        print(len(bills_with_this_no), "bills called", bill.billno)

        # User lists tracking each of the duplicate bills:
        userlists = []
        numusers = []

        mostusers = 0
        maxindex = None
        for i, dupbill in enumerate(bills_with_this_no):
            bill_ids_seen.add(dupbill.id)
            tracking = dupbill.users_tracking()
            howmany = len(tracking)
            userlists.append(tracking)
            numusers.append(howmany)
            if howmany > mostusers:
                mostusers = howmany
                maxindex = i

        # Now bills_with_this_no is a list of Bill objects.
        # userlists is a list of lists of User objects tracking each bill.
        # numusers is a list of lists of how many users are tracking each bill.
        # maxindex is the index in all three lists of the bill that's
        # tracked by the most users; we'll make that the real bill
        # and remove the rest.
        if maxindex == None:
            print("  No users are tracking %s!" % bill.billno)

        # print("  Master bill, id %d, tracked by %s" % (bills_with_this_no[maxindex].id, ', '.join([u.username for u in userlists[maxindex]])))
        # print("  Duplicates:")
        # for i, b in enumerate(bills_with_this_no):
        #     if i == maxindex:
        #         continue
        #     if userlists[i]:
        #         print("    id %d tracked by %s" % (bills_with_this_no[i].id,
        #                                            ', '.join([u.username for u in userlists[i]])))
        #     else:
        #         print("    id %d, no users" % bills_with_this_no[i].id)

        # Now it's time to actually fix the problem.
        masterbills.append(bill)

        return masterbills


@billtracker.route('/api/showdups/<key>')
def show_dups(key):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    masterbills = find_dups()

    if not masterbills:
        print("No duplicate bills in database, whew")
        return "OK"

    print("masterbills:", masterbills)

    return "OK %s" % ','.join([ b.billno for b in masterbills ])


# TEMPORARY, clean out duplicates
@billtracker.route('/api/cleandups/<key>')
def clean_dups(key):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    masterbills = find_dups()

    if not masterbills:
        print("No duplicate bills in database, whew")
        return "OK"

    print("masterbills:", masterbills)

    # Now make a separate loop, so we're not changing the list of all bills
    # while looping over the list of all bills.
    for masterbill in masterbills:
        print("%s, master is id %d" % (masterbill.billno, masterbill.id))

        bills_with_this_no = Bill.query.filter_by(billno=masterbill.billno).all()
        print("  %d bills with this no: %s" % (len(bills_with_this_no),
                                       [b.id for b in bills_with_this_no]))

        for i, b in enumerate(bills_with_this_no):
            if b.id == masterbill.id:
                continue
            users = b.users_tracking()
            if users:
                print("  Moving id %d's users over to id %d: %s"
                      % (bills_with_this_no[i].id,
                         bills_with_this_no[maxindex].id,
                         [u.username for u in users]))
                for u in users:
                    if b not in u.bills:
                        print("Eek, id %d thinks %s is tracking but %s doesn't think so" % (b.id, u.username))
                        continue
                    if masterbill not in u.bills:
                        u.bills.append(masterbill)
                        print("    moved %s" % u.username)
                    else:
                        print("    %s was already tracking %d" % (u.username,
                                                                masterbill.id))
                    u.bills.remove(b)
                    db.session.add(u)
            else:
                print("  id %d had no users" % b.id)

            print("  Deleting bill id %d" % b.id)
            db.session.delete(b)

        db.session.add(masterbill)

    if masterbills:
        db.session.commit()
    return "OK"
