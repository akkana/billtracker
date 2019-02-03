from flask import render_template, flash, redirect, url_for, request, jsonify
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse

from app import app, db
from app.forms import LoginForm, RegistrationForm, AddBillsForm, \
    UserSettingsForm, PasswordResetForm
from app.models import User, Bill
from app.bills import nmlegisbill, billutils
from .emails import daily_user_email, send_email
from config import ADMINS

from datetime import datetime, timedelta
import json
import requests
import collections
import random
import multiprocessing
import posixpath
import traceback
import sys, os


# A dictionary used by /api/onebill, for the AJAX updating:
# keys are all the usernames currently updating their bill lists,
# values are a list of all billids not yet updated.
# XXX If something goes wrong with this, how do we remove the user from
# the queue? Maybe have to pass in some sort of "first_time" variable.
users_updating = {}


@app.route('/')
@app.route('/index')
@login_required
def index():
    # Make sure any AJAX updates start from scratch:
    try:
        del users_updating[current_user.username]
    except:
        pass

    return render_template('index.html', title='Home')


@app.route('/login', methods=['GET', 'POST'])
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


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


# The mega tutorial called this /register,
# but flask seems to have a problem calling anything /register.
# As long as it's named something else, this works.
@app.route('/newaccount', methods=['GET', 'POST'])
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


@app.route('/confirm_email/<auth>')
def confirm_email(auth):
    user = User.query.filter_by(auth_code=auth).first()
    if not user:
        flash("Sorry, I don't know that code. Please contact an administrator.")
        return redirect(url_for('user_settings'))

    # Correct code. Hooray!
    user.confirm_email()
    flash("Your email address is now confirmed.")
    return redirect(url_for('login'))


@app.route('/about')
def about():
    return render_template('about.html', title='About NMBillTracker')


@app.route('/addbills', methods=['GET', 'POST'])
@login_required
def addbills():
    user = User.query.filter_by(username=current_user.username).first()
    form = AddBillsForm()

    if form.validate_on_submit():
        billno = form.billno.data
        # do stuff with valid form
        # then redirect to "end" the form
        # return redirect(url_for('addbills'))
        bill = Bill.query.filter_by(billno=billno).first()
        if bill:
            # But is the user already following it?
            if bill in user.bills:
                flash("You're already following " + billno)
                return redirect(url_for('addbills'))
        else:
            # It's a bill not in the database yet: fetch it.
            b = nmlegisbill.parse_bill_page(billno,
                                            year=datetime.now().year,
                                            cache_locally=True)

            if b:
                bill = Bill()
                bill.set_from_parsed_page(b)

                try:
                    db.session.add(bill)
                except:
                    flash("Couldn't add %s to the database" % billno)
                    print("Couldn't add %s to the database" % billno,
                          file=sys.stderr)
            else:
                bill = None
                flash("Couldn't fetch information for %s" % billno)

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
@app.route('/unfollow', methods=['GET', 'POST'])
@login_required
def unfollow():
    if request.method == 'POST' or request.method == 'GET':
        # request contains form (for POST), args (for GET),
        # and values (combined); the first two are ImmutableMultiDict,
        # values is CombinedMultiDict.
        # I've found no way to iterate through
        # either ImmutableMultiDict or CombinedMultiDict;
        # to_dict() is the only way I've found of accessing the contents.

        unfollow = []
        values = request.values.to_dict()
        for billno in values:
            if values[billno] == 'on':
                if billno[0] not in 'SHJ':
                    continue
                unfollow.append(billno)
        if unfollow:
            user = User.query.filter_by(username=current_user.username).first()
            newbills = []
            for bill in user.bills:
                if bill.billno not in unfollow:
                    newbills.append(bill)
            user.bills = newbills
            db.session.add(user)
            db.session.commit()

            flash("Unfollowed " + ','.join(unfollow))

    return redirect(url_for('addbills'))


@app.route('/allbills')
@login_required
def allbills():
    '''Show all bills that have been filed, with titles and links,
       whether or not they're in our database or any user is tracking them.
       New bills the user hasn't seen before are listed first.
    '''
    user = User.query.filter_by(username=current_user.username).first()
    if user.bills_seen:
        bills_seen = user.bills_seen.split(',')
    else:
        bills_seen = []

    allbills = nmlegisbill.all_bills()
    # This is an OrderedDic, billno: title

    newlines = []
    oldlines = []
    for billno in allbills:
        args = [billno, allbills[billno][0], allbills[billno][1],
                nmlegisbill.contents_url_for_billno(billno)]
        if billno not in bills_seen:
            newlines.append(args)
        else:
            oldlines.append(args)

    # Update user
    user.bills_seen = ','.join(allbills.keys())
    db.session.add(user)
    db.session.commit()

    return render_template('allbills.html',
                           newlines=newlines, oldlines=oldlines)


@app.route("/config")
@login_required
def config():
    if current_user.email not in ADMINS:
        flash("Sorry, this page is only available to administrators.")
        return render_template('config.html', users=None)

    return render_template('config.html', users=User.query.all())


@app.route("/settings", methods=['GET', 'POST'])
def user_settings():
    form = UserSettingsForm(obj=current_user)

    if form.validate_on_submit():
        newpasswd = form.password.data
        email = form.email.data
        updated = []

        if newpasswd:
            current_user.set_password(newpasswd)
            updated.append("password")

        if email:
            # Make sure the new email address is unique:
            u = User.query.filter_by(email=email).first()
            if u and u != current_user:
                flash("Sorry, that email address is not available")
                return render_template('settingshtml', form=form)

            current_user.email = email
            updated.append("email")

        if updated:
            db.session.add(current_user)
            db.session.commit()
            flash("Updated " + ' and '.join(updated))
            if "email" in updated:
                print("Sending confirmation mail, I hope")
                current_user.send_confirmation_mail()
                flash("Sent confirmation mail")

    return render_template('settings.html', form=form)


@app.route("/password_reset", methods=['GET', 'POST'])
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

@app.route("/api/all_daily_emails/<key>")
def all_daily_emails(key):
    '''Send out daily emails to all users with an email address registered.
       A cron job will visit this URL once a day.
    '''
    if key != app.config["SECRET_KEY"]:
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


@app.route('/api/mailto/<username>/<key>')
def mailto(username, key):
    if key != app.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    user = User.query.filter_by(username=username).first()
    if not user:
        return "FAIL Couldn't get user for %s\n" % username

    if not user.email:
        return "FAIL %s doesn't have an email address registered.\n" % username

    print("Attempting to send email to", user.username)
    try:
        daily_user_email(user)
    except Exception as e:
        print("Error, couldn't send email to %s" % username, file=sys.stderr)
        print(e, file=sys.stderr)
        print(traceback.format_exc())
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
#               { "BILLNO": billno, "KEY": key }).text
#
@app.route("/api/refresh_one_bill", methods=['POST'])
def refresh_one_bill():
    '''Long-running query: fetch the page for a bill and update it in the db.
       Send the billno as BILLNO and the app key as KEY in POST data.
    '''
    key = request.values.get('KEY')
    if key != app.config["SECRET_KEY"]:
        return "FAIL Bad key\n"
    billno = request.values.get('BILLNO')

    now = datetime.now()
    b = nmlegisbill.parse_bill_page(billno, year=now.year, cache_locally=True)
    if not b:
        return "FAIL Couldn't fetch %s bill page" % billno

    bill = Bill.query.filter_by(billno=billno).first()
    if not bill:
        bill = Bill()

    bill.set_from_parsed_page(b)
    print("Updated", bill)
    db.session.add(bill)
    db.session.commit()

    return "OK Updated %s" % billno


@app.route("/api/bills_by_update_date")
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
# posturl = '%s/api/update_legisdata' % baseurl
# lescdata = { "TARGET": "LESClink",
#              "URL": "ftp://www.nmlegis.gov/LESCAnalysis",
#              "KEY"='...' }
# firdata = { "TARGET": "FIRlink", "URL": "ftp://www.nmlegis.gov/firs",
#             "KEY"='...' }
# amenddata = { "TARGET": "amendlink",
#               "URL": "ftp://www.nmlegis.gov/Amendments_In_Context",
#               "KEY"='...' }
# requests.post(posturl, xyzdata).text
@app.route("/api/update_legisdata", methods=['POST'])
def update_legisdata():
    '''Fetch a file from the legislative website in a separate thread,
       which will eventually update a specific field in the bills database.
       POST data required:
         TARGET is the field to be changed (e.g. FIRlink);
         URL is the ftp index for that link, e.g. ftp://www.nmlegis.gov/firs/
         KEY is the app key.
    '''
    key = request.values.get('KEY')
    if key != app.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    url = request.values.get('URL')
    target = request.values.get('TARGET')
    print("update_legisdata %s from %s" % (target, url))

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
        print("base", base)

        # filenames are e.g. HB0032.PDF. Remove zeros.
        billno = base.replace('0', '')
        print("billno", billno)
        bill = Bill.query.filter_by(billno=billno).first()
        if bill:
            print("bill", bill)
            setattr(bill, target, posixpath.join(url, filename))
            db.session.add(bill)
            changes.append(billno)
        else:
            print("%s isn't in the database" % billno)

    if not changes:
        return "OK but no bills updated"

    db.session.commit()
    return "OK Updated " + ','.join(changes)
