from flask import render_template, flash, redirect, url_for, request
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse

from app import app, db
from app.forms import LoginForm, RegistrationForm, AddBillsForm
from app.models import User, Bill
from app.bills import nmlegisbill
from .emails import daily_user_email

from datetime import datetime
import json
import collections
import sys


@app.route('/')
@app.route('/index')
@login_required
def index():
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
# I'm not sure why there are methods defined here,
# nothing's passed to this page.
@app.route('/newaccount', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

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
        print("addbills(): billno =", billno, file=sys.stderr)
        # do stuff with valid form
        # then redirect to "end" the form
        # return redirect(url_for('addbills'))
        bill = Bill.query.filter_by(billno=billno).first()
        if bill:
            print("Woohoo, we already know about bill", billno,
                  file=sys.stderr)

            # But is the user already following it?
            if bill in user.bills:
                flash("You're already following " + billno)
                return redirect(url_for('addbills'))
        else:
            # It's a bill not in the database yet: fetch it.
            b = nmlegisbill.parse_bill_page(billno,
                                            year=datetime.now().year,
                                            cache_locally=True)

            bill = Bill(**b)

            try:
                db.session.add(bill)
            except:
                print("Couldn't add %s to the database" % billno,
                      file=sys.stderr)
                sys.exit(1)

        # Either way, bill should be set to a Bill object now.
        # Add it to the current user:
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

            flash("Unfollowed " + ", ".join(unfollow))

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
        if billno not in bills_seen:
            newlines.append([billno, allbills[billno][0], allbills[billno][1]])
        else:
            oldlines.append([billno, allbills[billno][0], allbills[billno][1]])

    # Update user
    user.bills_seen = ','.join(allbills.keys())
    db.session.add(user)
    db.session.commit()

    return render_template('allbills.html',
                           newlines=newlines, oldlines=oldlines)


@app.route("/api/all_daily_emails")
def all_daily_emails():
    '''Send out daily emails to all users with an email address registered.
       A cron job will visit this URL once a day.
    '''
    for user in User.query.all():
        if user.username != 'akkana':
            print("%s is not akkana, skipping" % user.username)
            continue

        if not user.email:
            print("%s doesn't have an email address" % user.username)
            continue

        print("User %s's bills are: %s" % (user.username,
                                      ', '.join([str(b) for b in user.bills])))
        mailto(user.username)

    return "OK"

@app.route('/api/mailto/<username>')
def mailto(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        flash("Couldn't get user for " + username)
        return redirect(url_for('mailto'))

    if not user.email:
        flash("%s doesn't have an email address registered." % username)
        return redirect(url_for('mailto'))

    print("Attempting to send email to", user.username)
    # daily_user_email(user)

    user.last_check = datetime.now()
    db.session.add(user)
    db.session.commit()

    return render_template('send_mail.html', title='Send Email', user=user)


# This next method is mostly for testing and will go away soon.
# I don't expect it to be very useful for users.
# Normally, emails will be scheduled to be sent once a day.

@app.route('/sendmail')
@login_required
def sendmail():
    return mailto(current_user.username)


#
# Gradual bill updating using AJAX.
#

# A dictionary: keys are all the usernames currently updating their bill lists,
# values are a list of all billids not yet updated.
# XXX If something goes wrong with this, how do we remove the user from
# the queue? Maybe have to pass in some sort of "first_time" variable.
users_updating = {}

@app.route("/api/onebill/<username>")
def onebill(username):
    '''Returns JSON.
    '''
    global users_updating

    if not username:
        return "No username specified!"

    user = User.query.filter_by(username=username).first()
    if not user:
        return "Unknown user: " + username

    # Are we already updating this user?
    billids = None
    for un in users_updating:
        if un == username:
            billids = users_updating[username]
            break
    else:    # Not already updating this username
        billids = [b.id for b in user.bills]
        users_updating[username] = billids

    # Now user and billids are set.
    if not billids:
        del users_updating[username]
        return json.dumps({
            "summary"  : "(No more)",
            "more"      : False
        })

    billid = billids.pop(0)
    bill = Bill.query.filter_by(id=billid).first()

    # Check whether the bill wants to update itself:
    if bill.update():
        db.session.add(bill)
        db.session.commit()

    # Is the bill changed as far as the user is concerned?
    now = datetime.now()
    oneday = 24 * 60 * 60    # seconds in a day
    if (bill.last_action_date and (
            bill.last_action_date > user.last_check or
            (now - bill.last_action_date).seconds < oneday)):
        changep = True
    else:
        changep = False

    return json.dumps({
        "summary"  : bill.show_html(True),
        "changed"  : changep,
        "more"     : len(billids) > 0
        })

