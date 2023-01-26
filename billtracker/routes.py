from flask import render_template, flash, redirect, url_for, request, jsonify
from flask import session
from flask import request
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse

from billtracker import billtracker, db
from billtracker import chattycaptcha
from billtracker.forms import LoginForm, RegistrationForm, AddBillsForm, \
    UserSettingsForm, PasswordResetForm, EmailBlastForm
from billtracker.models import User, Bill, Legislator, Committee, LegSession
from billtracker.bills import nmlegisbill, billutils, billrequests
from .emails import daily_user_email, send_email
from config import ADMINS

from datetime import datetime, timedelta, timezone, date

import json
import requests
import random
import multiprocessing
import posixpath
import traceback
import shutil
import subprocess
import re
from collections import OrderedDict
import colorsys
import hashlib
import sys, os


# filenames are e.g. HB000032.PDF with a random number of zeros.
# Remove all zeros -- but not in the middle of a number, like 103.
billno_pat = re.compile("([A-Z]*)(0*)([1-9][0-9]*)")


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


def initialize_captcha():
    if chattycaptcha.initialized():
        return

    chattycaptcha.init_captcha(os.path.join(billrequests.CACHEDIR,
                                            "CAPTCHA-QUESTIONS"))


# The mega tutorial called this /register,
# but flask seems to have a problem calling anything /register.
# As long as it's named something else, this works.
@billtracker.route('/newaccount', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    initialize_captcha()

    if "capq" not in session:
        session["capq"] = chattycaptcha.random_question()

    form = RegistrationForm()

    # This function is called in two ways.
    # It's called to display the form in the first place,
    # in which case form.validate_on_submit() is false,
    # but then when the form is submitted after the validations built
    # into the form have passed, register() is called again
    # with form.validate_on_submit() true.
    if not form.validate_on_submit():
        # Just displaying the form.
        # Don't change the captcha question, but initialize it if needed.
        if not form.capq.data:
            if "capq" in session:
                form.capq.data = session["capq"]
            else:
                session["capq"] = chattycaptcha.random_question()
                form.capq.data = session["capq"]

        return render_template('register.html', title='Register', form=form)

    # The form has been submitted and validated.
    # We just called validate_on_submit(), which reloaded the form,
    # then called the various validate() methods AFTER reloading.
    print("Creating new user account", form.username.data,
          "from IP", request.remote_addr,
          "with captcha", session["capq"],
          file=sys.stderr)
    user = User(username=form.username.data, email=form.email.data)
    user.set_password(form.password.data)

    if user.email:
        try:
            print("Sending confirmation mail to", form.username.data)
            user.send_confirmation_mail(request.url_root)
            flash("Welcome to the NM Bill Tracker. A confirmation message has been mailed to %s."
                  % user.email)
        except Exception as e:
            print(e, file=sys.stderr)
            print("Couldn't send confirmation mail to", user.email,
                  file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            flash("You're registered! But something went wrong trying to send you a confirmation mail, so your email address won't work yet. Please contact an administrator. Sorry about that!")
    else:
        flash('Welcome to the NM Bill Tracker.')

    db.session.add(user)
    db.session.commit()

    # Now reset the captcha question.
    if "capq" in session:
        session["capq"] = chattycaptcha.random_question(session["capq"])

    return redirect(url_for('login'))


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

    # Make sure the bill doesn't already exist.
    # This happens sometimes, maybe due to a race condition
    # but I haven't tracked it down yet.
    bills = Bill.query.filter_by(billno=billno, year=yearcode).all()
    if bills:
        print(traceback.format_exc(), file=sys.stderr)
        print("**** Warning: make_new_bill called for bill that already existed",
              file=sys.stderr)
        for b in bills:
            print("    %s (id %d)" % (str(bill), bill.id), file=sys.stderr)
        print("See preceding traceback", file=sys.stderr)

        return bills[0]

    b = nmlegisbill.parse_bill_page(billno, yearcode=yearcode,
                                    cache_locally=True)
    if not b:
        return None

    bill = Bill()
    bill.set_from_parsed_page(b)

    # Immediately commit, to reduce (though not entirely eliminate)
    # race conditions
    db.session.add(bill)
    db.session.commit()

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
        bills_created = []
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
            else:    # Not in the database yet
                try:
                    bill = make_new_bill(billno, session["yearcode"])
                    if bill:
                        bills_created.append(bill)
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

                # Now that it's committed, check for a dup
                bs = Bill.query.filter_by(billno=billno,
                                          year=session["yearcode"]).all()
                if len(bs) > 1:
                    print("YIKES! addbills reated a duplicate bill",
                          file=sys.stderr)
                    for b in bs:
                        print("   ", b, file=sys.stderr)
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
# WTForms doesn't have any way to allow adding variable
# numbers of checkboxes, so this is an old-school form.
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

        values = request.values.to_dict()

        if 'returnpage' in values:
            returnpage = values['returnpage']
        else:
            returnpage = 'addbills'

        set_session_by_request_values(values)

        # Loop over checkboxes to see what tracking changes are needed.
        # The form will only include checked bills; if there are any
        # that the user un-checked, those can be detected as bills
        # the user is currently following that don't have a corresponding
        # f_billno checkbox in values.
        now_tracking = set([ b.billno
            for b in current_user.bills_by_yearcode(session["yearcode"]) ])
        will_track = set()
        will_untrack = set()
        for btnno in values:
            if btnno.startswith('f_'):
                billno = btnno[2:]
                if values[btnno] == 'on':
                    will_track.add(billno)

            elif btnno.startswith('u_'):
                billno = btnno[2:]
                if values[btnno] == 'on':
                    will_untrack.add(billno)

        track_bills = will_track - now_tracking
        if will_untrack:    # Pages that have u_ unfollow checkboxes, if any
            untrack_bills = will_untrack
        else:
            # Most pages that use this route have a single button per bill,
            # f_billno, and if it's checked it means follow, unchecked means
            # unfollow. But forms don't submit unchecked bill numbers, so
            # if there are no u_billno unfollow buttons, we have to assume
            # that anything that's not explicitly checked should be unfollowed.
            untrack_bills = now_tracking - will_track

        # print("Will track", track_bills)
        # print("Will untrack", untrack_bills)

        if not track_bills and not untrack_bills:
            return redirect(url_for(returnpage))

        if untrack_bills:
            for b in current_user.bills_by_yearcode(session["yearcode"]):
                if b.billno in untrack_bills:
                    current_user.bills.remove(b)
            untrack_bills = sorted(list(untrack_bills))
            flash("You are no longer tracking %s" % ', '.join(untrack_bills))

        # The hard (and slow) part: make new bills as needed.
        # Can't really do this asynchronously (unless it's with AJAX)
        # since the user is waiting.
        # However, querying Bill.query.filter_by apparently holds
        # the database locked open, keeping anyone else from writing it
        # while make_new_bill fetches info.

        if track_bills:
            # Figure out which bills will need to be fetched:
            # Bills the user wants to track that don't exist yet in the db:
            new_billnos = []
            # Bills that the user will start tracking:
            bills_to_track = []
            for billno in track_bills:
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
            track_bills = sorted(list(track_bills))
            flash("You are now tracking %s" % ', '.join(track_bills))

            # Now add all the bills to track to the user's list
            # (hitting the database):
            for bill in bills_to_track:
                current_user.bills.append(bill)
            for bill in new_bills:
                db.session.add(bill)
                current_user.bills.append(bill)

        if track_bills or untrack_bills:
            # We changed something. Finish up and commit.
            db.session.add(current_user)
            db.session.commit()
 
        for billno in track_bills:
            # Now that it's committed, check for a dup
            bs = Bill.query.filter_by(billno=billno,
                                      year=session["yearcode"]).all()
            if len(bs) > 1:
                print("YIKES! track_untrack created a duplicate bill",
                      file=sys.stderr)
                for b in bs:
                    print("   ", b, file=sys.stderr)

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
    leg_session = LegSession.by_yearcode(session["yearcode"])

    bill_list = Bill.query.filter_by(year=session["yearcode"]).all()
    bill_list.sort(key=lambda b: b.num_tracking(), reverse=True)
    bill_list = [ b for b in bill_list if b.num_tracking() > 0 ]
    return render_template('popular.html',
                           yearcode=session["yearcode"],
                           user=current_user,
                           bill_list=bill_list)


@billtracker.route('/allbills')
def allbills():
    """Show all bills that have been filed in the given session,
       with titles and links,
       whether or not they're in our database or any user is tracking them.
       (Bills are only added to the database once someone tracks them.)
       New bills the user hasn't seen before are listed first.
    """
    set_session_by_request_values()
    yearcode = session["yearcode"]
    leg_session = LegSession.by_yearcode(yearcode)
    if not leg_session:
        LegSession.update_session_list()
        leg_session = LegSession.by_yearcode(yearcode)
        if not leg_session:
            flash("Error getting the list of legislative sessions")
            print("*** Error getting the list of legislative sessions!",
                  file=sys.stderr)
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

    # Now sort both dicts; the allbills page will display the order
    # passed in, in each case.
    def dic_to_key(dic):
        match = re.match(billno_pat, dic["billno"])
        if not match:
            return "X" + billno
        billtype, zeros, num = match.groups()
        return billtype + num.zfill(5)

    newbills.sort(key=dic_to_key)
    oldbills.sort(key=dic_to_key)

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
                           bill_lists=bill_lists,
                           showtags=False)


def get_all_tags(yearcode):
    all_tags = set()
    for bill in Bill.query.filter_by(year=yearcode).all():
        if bill.tags:
            for tag in bill.tags.split(','):
                all_tags.add(tag)

    return sorted(list(all_tags), key=lambda t: t.lower())


# tags is another route that bypasses WTForms in order to have a bill list
# with checkboxes.
@billtracker.route("/tags", defaults={'tag': None}, methods=['GET', 'POST'])
@billtracker.route("/tags/<tag>", methods=['GET', 'POST'])
def tags(tag=None):
    values = request.values.to_dict()
    set_session_by_request_values()

    bill_list = Bill.query.filter_by(year=session["yearcode"]).all()
    bill_list.sort()

    def is_legal_tag(tagname):
        """Is tagname a legal tag name?"""
        if len(tagname) > 15:
            return False
        if re.match('^[A-Za-z0-9\-]+$', tagname):
            return True
        return False

    badtag = None

    # Was this a form submittal?
    # The form has two submit buttons, with names "submitnewtag" for
    # the new tag input field and "update" to update the buttons for
    # the current tag. Figure out which path the user followed:
    if current_user and not current_user.is_anonymous:
        if "update" in request.form:
            tag = values["tag"]
            if not is_legal_tag(tag):
                flash("'%s' isn't a legal tag name" % tag)
            else:
                bills_added = []
                bills_removed = []
                bills_tagged = 0

                for bill in bill_list:
                    if bill.tags:
                        billtags = bill.tags.split(',')
                    else:
                        billtags = []

                    # Newly checked?
                    if tag not in billtags and "f_%s" % bill.billno in values:
                        billtags.append(tag)
                        bill.tags = ','.join(billtags)
                        db.session.add(bill)
                        bills_added.append(bill.billno)

                    # Newly unchecked?
                    elif tag in billtags and "f_%s" % bill.billno not in values:
                        billtags.remove(tag)
                        bill.tags = ','.join(billtags)
                        db.session.add(bill)
                        bills_removed.append(bill.billno)

                    if tag in billtags:
                        bills_tagged += 1

                if bills_added:
                    flash(','.join(bills_added) + " now tagged '%s'" % tag)
                if bills_removed:
                    flash(','.join(bills_removed) + " no longer tagged '%s'" % tag)
                if bills_added or bills_removed:
                    print(current_user.username, "tagged", len(bills_added),
                          "and untagged", len(bills_removed), "as", tag,
                          file=sys.stderr)
                    db.session.commit()
                if not bills_tagged:
                    flash("No remaining bills tagged '%s': tag has been removed"
                          % tag)
                    print(current_user, "removed all '%s' tags" % tag,
                          file=sys.stderr)

        elif "submitnewtag" in request.form:
            if values["newtag"]:
                if is_legal_tag(values["newtag"]):
                    tag = values["newtag"]
                    flash("Now choose some bills to tag with new tag '%s'"
                          % tag)
                    print(current_user, "created tag '%s'" % tag,
                          file=sys.stderr)
                else:
                    tag = None
                    badtag = values["newtag"]
                    flash("%s' isn't a legal tag name. Only letters, numbers, dash, 15 characters max" % badtag)

    # Now retagging is finished. Group bills according to whether
    # they're tagged with the current tag (or at all).
    tagged = []
    untagged = []
    for bill in bill_list:
        if not bill.num_tracking():
            continue
        if not bill.tags:
            untagged.append(bill)
            continue

        billtags = bill.tags.split(',')

        # If this page is for all tags, show bills that have any tag,
        # but no untagged bills.
        if not tag:
            tagged.append(bill)

        # If the page is showing a specific tag,
        # group bills according to whether they have that tag.
        elif tag in billtags:
            tagged.append(bill)
        else:
            untagged.append(bill)

    if tag:
        bill_lists = {
            "Tagged with '%s'" % tag: tagged,
            "Not %s" % tag: untagged
        }
    else:
        bill_lists = {
            "Bills with tags": tagged,
            "Not tagged": untagged
        }

    def str2color(instr):
        """
        Convert an arbitrary-length string to a CSS style string
        like "background: '#0ff'".
        Return a dictionary, { instr: css_color_code }
        Try to keep them light, so dark text will contrast well.
        If there are commas in the tag string, loop over them.
        """
        if ',' in instr:
            pieces = instr.split(',')
        else:
            pieces = [ instr ]

        dic = {}

        for piece in pieces:
            sixbytes = hashlib.sha256(piece.encode()).hexdigest()[:6]
            # hue can be anything between 0 and 1
            h = int(sixbytes[0:2], 16) / 256.
            # lightness between .8 and .88
            l = int(sixbytes[0:2], 16) / 2048 + .8
            # saturation between 0 and .5
            s = int(sixbytes[2:4], 16) / 256.

            rgb = colorsys.hls_to_rgb(h, l, s)

            # rgb = tuple((int((ord(c.lower())-97)*256./26) for c in s[:3]))
            rgb = tuple((int(x * 256) for x in rgb))

            dic[piece] = "#%02x%02x%02x" % rgb

        return dic

    return render_template('tags.html', user=current_user,
                           yearcode=session["yearcode"],
                           bill_lists=bill_lists,
                           tag=tag, badtag=badtag,
                           colorfcn=str2color,
                           alltags=get_all_tags(session["yearcode"]))


@billtracker.route("/config")
@login_required
def config():
    if current_user.email not in ADMINS:
        flash("Sorry, this page is only available to administrators.")
        return render_template('config.html', users=None)

    return render_template('config.html', users=User.query.all())


@billtracker.route("/changesession")
def changesession():
    cursession = None
    if "yearcode" in session:
        cursession = LegSession.by_yearcode(session["yearcode"])
    if not cursession:
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
            current_user.send_confirmation_mail(request.url_root)
            flash("Sent confirmation mail")

    return render_template('settings.html', form=form)


@billtracker.route("/password_reset", methods=['GET', 'POST'])
def password_reset():
    form = PasswordResetForm()

    if not form.validate_on_submit():
        # initial display, or validation error.
        # Set the captcha q.
        initialize_captcha()
        if not form.capq.data:
            if "capq" in session and session["capq"]:
                form.capq.data = session["capq"]
            else:
                session["capq"] = chattycaptcha.random_question()
                form.capq.data = session["capq"]

        return render_template('passwd_reset.html', title='Password Reset',
                           form=form)

    # The form was validated and submitted
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
        passwdlen = 11
        for i in range(passwdlen):
            newpasswd += random.choice(charset)

        user.set_password(newpasswd)
        db.session.add(user)
        db.session.commit()

        print("Sending password reset email to %s, password %s"
              % (user.email, newpasswd),
              ": captcha was", session["capq"],
              file=sys.stderr)
        send_email("NM Bill Tracker Password Reset",
                   "noreply@nmbilltracker.com", [ user.email ],
                   render_template("passwd_reset.txt",
                                   username=user.username,
                                   email=user.email,
                                   newpasswd=newpasswd))

        flash("Mailed a new password to %s" % user.email)

        # Now reset the captcha question.
        session["capq"] = chattycaptcha.random_question(session["capq"])

    else:
        # Missing user or user.email
        print("WARNING: unsuccessful attempt to reset password for email",
              email, file=sys.stderr)
        flash("Sorry, no email address %s is registered" % email)

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
    never_checked = []
    no_bills = []
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
            never_checked.append(user)

        numbills = len(user.bills)
        if numbills:
            totbills += numbills
            for bill in user.bills:
                if bill.year == yearcode:
                    has_current_year_bills += 1
                    break
        else:
            no_bills.append(user)

    infostr += "<br>\n%swith bills from this session: %d" % (spacer,
                                                      has_current_year_bills)
    infostr += "<br>\n%schecked in past day: %d" % (spacer,
                                                    checked_in_last_day)
    infostr += "<br>\n%snever checked: %d" % (spacer, len(never_checked))
    for user in never_checked:
        infostr += " " + user.username

    infostr += "<br>\n%sno bills in any session: %d" % (spacer, len(no_bills))
    for user in no_bills:
        infostr += " " + user.username

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


@billtracker.route("/api/blastemail/<key>", methods=['GET', 'POST'])
def blast_email(key):
    """Blast an email to all registered billtracker users"""

    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    form = EmailBlastForm()

    if form.validate_on_submit():
        print("form validated")
        # This shouldn't be possible because the form should have already
        # validated the key, but let's be extra cautious with email blasts:
        if form.key.data != billtracker.config["SECRET_KEY"]:
            return "FAIL Bad key\n"

        # Build list of recipients
        recipients = []
        for user in User.query.all():
            if not user.email:
                print("%s doesn't have an email address: not sending email"
                      % user.username, file=sys.stderr)
                continue

            if not user.email_confirmed():
                print("%s has an unconfirmed email address: not sending."
                      % user.username, file=sys.stderr)
                continue

            recipients.append([user.username, user.email])

        # Actually send the email
        subject = "New Mexico BillTracker"
        for username, email in recipients:
            body = "Hi, %s,\n\n" % username + form.body.data
            send_email(subject, "noreply@nmbilltracker.com",
                       [email], body, None)

        return("OK Sent email to %s" % ' '.join([r[1] for r in recipients]))

    return render_template("blastemail.html", form=form)


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
    """Fetch the page for a bill and update it in the db.
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

# Test with:
# requests.post('%s/api/refresh_percent_of_bills' % baseurl,
#               { "PERCENT": percent, "YEAR": year, "KEY": key }).text
# requests.post('%s/api/refresh_percent_of_bills' % baseurl,
#               { "PERCENT": percent, "YEARCODE": yearcode, "KEY": key }).text
@billtracker.route("/api/refresh_percent_of_bills", methods=['GET', 'POST'])
def refresh_percent_of_bills():
    """Refresh a given percentage of the bill list
       for a specified yearcode or year.
       If a year is given, refresh that percentage of bills
       within all yearcodes from that year.
       This is necessary because a special session may be called
       before all the bills from the previous session have been signed.
       If neither yearcode nor year is specified, refresh the current year.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_one_bill: bad key %s" % key, file=sys.stderr)
        return "FAIL Bad key\n"

    percent = request.values.get("PERCENT")
    if percent:
        try:
            percent = int(percent)
        except ValueError:
            return "FAIL: Don't understand '%s' PERCENT" % percent

    yearcode = request.values.get('YEARCODE')
    if yearcode:
        yearcode_list = [ yearcode ]
    else:
        year = request.values.get('YEAR')
        if not year:
            yearcode = LegSession.current_yearcode()
            if len(yearcode) < 2:
                return "FAIL Can't get current yearcode"
            year = yearcode[:2]
        yearcode_list = []
        allsessions = LegSession.query.order_by(LegSession.id).all()
        for ls in allsessions:
            yc = ls.yearcode
            if yc.startswith(year):
                yearcode_list.append(yc)

    # Now yearcode_list is a list of session names (yearcodes)
    retstr = "OK Refreshed %d%% of bills:" % percent
    for yearcode in yearcode_list:
        allbills = Bill.query.filter_by(year=yearcode) \
                             .order_by(Bill.update_date).all()
        if not allbills:
            print("No bills in", yearcode, file=sys.stderr)
            continue

        num2update = len(allbills) * percent // 100
        if not num2update:
            num2update = 1

        bill_list = allbills[:num2update]
        print("Updating %d%% of bills in %s (%s bills): %s"
              % (percent, yearcode, num2update,
                 ', '.join([b.billno for b in bill_list])),
              file=sys.stderr)

        updated_bills = []
        failed_updates = []
        for bill in bill_list:
            b = nmlegisbill.parse_bill_page(bill.billno, yearcode)
            if not b:
                print("Failed to refresh:", bill, file=sys.stderr)
                failed_updates.append(bill.billno)
                continue
            bill.set_from_parsed_page(b)
            updated_bills.append(bill)
            db.session.add(bill)

        retstr += "\n%4s: Updated %s" % (
            yearcode, ' '.join([b.billno for b in updated_bills]))
        if failed_updates:
            retstr += "\n      Failed to update: %s" % (
            ' '.join([str(b) for b in failed_updates]))

    db.session.commit()
    return retstr


# Test:
# SERVERURL/api/refresh_session_list?KEY=KEY
# requests.post('%s/api/refresh_session_list' % baseurl, { "KEY": KEY }).text
@billtracker.route("/api/refresh_session_list", methods=['POST', 'GET'])
def refresh_session_list():
    """Fetch Legislation_List (the same file that's used for allbills)
       and check the menu of sessions to see if there's a new one.
    """
    key = request.values.get('KEY')
    if key != billtracker.config["SECRET_KEY"]:
        print("FAIL refresh_session_list: bad key %s" % key, file=sys.stderr)
        return "FAIL Bad key\n"

    LegSession.update_session_list()
    return "OK Refreshed list of legislative sessions"


@billtracker.route("/api/bills_by_update_date", methods=['GET', 'POST'])
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
    # XXX the nmlegis parts of this function should move to bills/nmlegisbill
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
    return "OK Refreshed legislators"


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
        # all_committees = Committee.query.all()
        return "FAIL no committees in db"

    return ','.join([ c.code for c in all_committees ])


@billtracker.route("/api/refresh_all_committees/<key>")
def refresh_all_committees(key):
    """Update all committees based on the latest list of upcoming
       committee meetings. Update bills' scheduled_date.
    """
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"
    print("Refreshing all committees", file=sys.stderr)

    set_session_by_request_values()
    yearcode = session["yearcode"]
    thisyear = date.today().year

    # First update the legislators list:
    Legislator.refresh_legislators_list()

    known_committees = Committee.query.all()
    # known_commcodes = [ c.code for c in known_committees ]

    comm_mtgs = nmlegisbill.expand_committees()

    # Are there any new committees in comm_mtgs not yet in the database?
    for commcode in comm_mtgs:
        comm = Committee.query.filter_by(code=commcode).first()
        if not comm:
            newcomm = Committee()
            newcomm.code = commcode

            # Need to add the new committee to the database before refreshing,
            # to avoid sqlite3.IntegrityError: UNIQUE constraint failed
            db.session.add(newcomm)
            db.session.commit()
            # except that even after this,
            # Committee.query.filter_by(code=commcode).first()
            # sometimes returns None. Sigh.

            # Now it should be safe to refresh
            newcomm.refresh()

    print("api/refresh_all_committees", file=sys.stderr)

    hasmeetings = []
    nomeetings = []
    bills_with_committee = {}
    for comm in Committee.query.filter_by().all():
        if comm.code not in comm_mtgs or not comm_mtgs[comm.code]:
            comm.mtg_time = None
            nomeetings.append(comm.code)
            continue

        if "meetings" not in comm_mtgs[comm.code]:
            nomeetings.append(comm.code)
            continue

        # XXX Currently the Committee database object can only
        # handle one meeting at once, and this code doesn't yet
        # try to handle multiple meetings.

        # Sort this committee's by datetime. Items missing time will have
        # time of 00:00 and so will come before items with a
        # time on the same day.
        # comm_mtgs[comm.code]["meetings"].sort(
        #     key=lambda m: m["datetime"] if "datetime" in m else "zzz")

        # Now update the committee's comm.mtg_time (a string) to show
        # meeting time and details. mtg["timestr"] is a free-form string
        # like "1:30 PM  (or 15 minutes following the floor session)"
        timestrings = []
        updated_comm = False
        for mtg in comm_mtgs[comm.code]["meetings"]:
            # Ignore any meeting without datetime or bills field.
            if "datetime" not in mtg:
                nomeetings.append(comm.code)
                continue
            if "bills" not in mtg:
                nomeetings.append(comm.code)
                continue

            if "timestr" in mtg:
                timestr = mtg["timestr"]
                # May include other details like zoom and schedule links
            elif type(mtg["datetime"]) is datetime and mtg["datetime"].hour:
                timestr = mtg["datetime"].strftime("%H:%M")
            else:
                timestr = ""

            comm.mtg_time = timestr

            for billno in mtg["bills"]:
                if billno in bills_with_committee:
                    if comm.code not in bills_with_committee[billno]:
                        bills_with_committee[billno].append(comm.code)
                else:
                    bills_with_committee[billno] = [comm.code]

                bill = Bill.query.filter_by(billno=billno,
                                            year=yearcode).first()
                if bill:
                    bill.location = comm.code
                    if mtg['datetime']:
                        bill.scheduled_date = mtg['datetime']
                        updated_comm = True
                    else:
                        bill.scheduled_date = None
                    db.session.add(bill)

        if updated_comm:
            hasmeetings.append(comm.code)
            db.session.add(comm)
        else:
            nomeetings.append(comm.code)

        db.session.add(comm)

    # Having looped through all the meetings, now clean up any bills
    # that aren't scheduled any longer.

    # Remove any bills that used to be assigned to this committee
    # but no longer are (so they're not in billnos).
    unscheduled = []
    for bill in Bill.query.filter_by(year=yearcode).all():
        if bill.billno not in bills_with_committee:
            bill.scheduled_date = None
            db.session.add(bill)
            unscheduled.append(bill.billno)

    # XXX Sometimes there are joint committee meetings,
    # in which case a bill may be listed for more than
    # one committee. In that case, the bill's location
    # should be set from the bill's HTML page, which
    # means it should be re-parsed here.
    for billno in bills_with_committee:
        if billno in bills_with_committee and \
           len(bills_with_committee[billno]) > 1:
            print("***", billno, "is in multiple committees:",
                  ' '.join(bills_with_committee[billno]), file=sys.stderr)

    db.session.commit()

    billnos = sorted(list(bills_with_committee.keys()))
    unscheduled.sort()
    return "OK\n<br>Committees meeting: " + ",".join(hasmeetings) \
        + "\n<br>No meetings, or no followed bills: " \
        + ",".join(nomeetings) \
        + "\n<br>" \
        + "\n<br>Bills updated: " + " ".join(billnos) \
        + "\n<br>Bills not scheduled: " + " ".join(unscheduled)


def refresh_one_committee(comcode):
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


def find_dups(yearcode=None):
    """Return a list of all bills that have duplicate entries in the db:
       multiple bills for the same billno and year.
       Return a list of lists of bills.
       Return only the master bill for each billno.
    """

    # A list of all bills that have duplicates, same billno and year.
    dup_bill_lists = []
    bill_ids_seen = set()

    if yearcode:
        bills = Bill.query.filter_by(year=yearcode).all()
    else:
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
        dup_bill_lists.append(bills_with_this_no)

        for dupbill in bills_with_this_no:
            bill_ids_seen.add(dupbill.id)

    return dup_bill_lists


@billtracker.route('/api/showdups/<key>')
@billtracker.route('/api/showdups/<key>/<yearcode>')
def show_dups(key, yearcode=None):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    dup_bill_lists = find_dups(yearcode)

    if not dup_bill_lists:
        print("No duplicate bills in database, whew")
        return "OK No dups"

    print("duplicate bills:", dup_bill_lists, file=sys.stderr)

    retstr = "OK"

    for duplist in dup_bill_lists:
        # The master will be the first, the one with the smallest ID
        min_id = min([b.id for b in duplist])
        masterbill = Bill.query.filter_by(id=min_id).first()

        retstr += "\n%s: id %d tracked by %s" % (
            masterbill.billno, masterbill.id,
            ','.join([u.username for u in masterbill.users_tracking()])
        )

        for b in duplist:
            if b == masterbill:
                continue
            retstr += "\n  %s id %d tracked by (%s)" % (
                b, b.id,
                ','.join([u.username for u in b.users_tracking()])
            )

    return retstr


# Clean out duplicates.
# This shouldn't be needed, but somehow, duplicates appear.
@billtracker.route('/api/cleandups/<key>')
@billtracker.route('/api/cleandups/<key>/<yearcode>')
def clean_dups(key, yearcode=None):
    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    billdups = find_dups(yearcode)
    # billdups is a list of pairs/triples/whatever of bills
    # with the same billno and yearcode

    if not billdups:
        print("No duplicate bills in database, whew", file=sys.stderr)
        return "OK"

    print("billdups:", billdups, file=sys.stderr)
    outstr = "OK<br>\n"

    def trackstr(b):
        return ', '.join([u.username for u in b.users_tracking()])

    deleted = []
    for duplist in billdups:
        # The master will be the first, the one with the smallest ID
        min_id = min([b.id for b in duplist])
        masterbill = Bill.query.filter_by(id=min_id).first()

        outstr += "<br><br>\n\n** %s: id %d, tracked by %s" % (masterbill.billno,
                                                          masterbill.id,
                                                          trackstr(masterbill))
        for b in duplist:
            if b == masterbill:
                continue
            outstr += "<br>\n . . %s (id %d) tracked by %s" % (b.billno, b.id,
                                                            trackstr(b))
            for u in b.users_tracking():
                u.bills.remove(b)
                if masterbill not in u.bills:
                    u.bills.append(masterbill)
                    outstr += "<br>\n . . . . Moved %s to masterbill" % \
                        u.username

            if b.users_tracking():
                print("<br> . . . EEK, failed to remove users from id %d before deleting" % b.id)
            else:
                deleted.append(b)
                outstr += "<br>\n . . Deleting bill with id %d" % b.id
                db.session.delete(b)

        outstr += "<br>\n . Now master bill %d is tracked by: %s" % \
            (masterbill.id, trackstr(masterbill))

    db.session.commit()

    outstr += "<br><br>\nAll bills to delete: %s" % \
        ', '.join(["id %d" % b.id for b in deleted])

    print(outstr, file=sys.stderr)
    return outstr

