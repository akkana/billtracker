from flask import render_template, flash, redirect, url_for, request
from flask import session
from flask import request
from flask_login import login_user, logout_user, current_user, login_required

from app import app, db
from app import chattycaptcha
from app.forms import LoginForm, RegistrationForm, AddBillsForm, \
    NewTagsForm, UserSettingsForm, PasswordResetForm
from app.models import User, Bill, Legislator, Committee, LegSession
from app.bills import nmlegisbill, billutils, billrequests
from app.emails import send_email
from .routeutils import BILLNO_PAT, html_bill_table, make_new_bill, \
    g_all_tags, get_all_tags, group_bills_by_tag, set_session_by_request_values
from config import ADMINS

from datetime import datetime, timedelta, date

import json
import requests
from urllib.parse import urlsplit
import random
import multiprocessing
import posixpath
import traceback
import shutil
import subprocess
import re
from collections import OrderedDict, defaultdict
import colorsys
import hashlib
import sys, os


# How recently did a bill have to change to be on the "new"
# list on the allbills page?
DAYS_CONSIDERED_NEW = 1.2


#
# bills.html can be called with a variety of sort views.
# Set sortby to one of (status, action_date, passed)
#
sortnames = {
    'status': 'Status',
    'action_date': 'Last action',
    'passed': 'Passed'
}


@app.route('/')
@login_required
def slash():
    values = request.values.to_dict()
    set_session_by_request_values(values)

    bill_list= current_user.bills_by_yearcode(session["yearcode"])
    bill_table = html_bill_table(bill_list, sortby="status",
                                 yearcode=session["yearcode"])

    return render_template('bills.html', title='Home', bill_table=bill_table,
                           sortby='status', sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


# Make / the preferred URL; /index redirects to /
@app.route('/index')
def index_redirect():
    return redirect(url_for('bills'))


@app.route('/bills')
@app.route('/bills/<sortby>')
@login_required
def bills(sortby=None):
    values = request.values.to_dict()
    set_session_by_request_values(values)

    bill_list= current_user.bills_by_yearcode(session["yearcode"])
    bill_table = html_bill_table(bill_list, sortby=sortby,
                                 yearcode=session["yearcode"])

    return render_template('bills.html', title='Home', bill_table=bill_table,
                           sortby=sortby, sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


@app.route('/status_bills')
@login_required
def statusbills():
    return redirect(url_for('bills', sortby='status'))


@app.route('/action_date_bills')
@login_required
def activebills():
    values = request.values.to_dict()
    set_session_by_request_values(values)

    bill_list= current_user.bills_by_yearcode(session["yearcode"])
    bill_table = html_bill_table(bill_list, sortby='action_date',
                                 yearcode=session["yearcode"])

    return render_template('bills.html', title='Home', bill_table=bill_table,
                           sortby='action_date', sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


@app.route('/passed_bills')
@login_required
def passedbills():
    values = request.values.to_dict()
    set_session_by_request_values(values)

    bill_list= current_user.bills_by_yearcode(session["yearcode"])
    bill_table = html_bill_table(bill_list, sortby='passed',
                                 yearcode=session["yearcode"])

    return render_template('bills.html', title='Home', bill_table=bill_table,
                           sortby='passed', sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


@app.route('/tagged_bills/<tag>')
@app.route('/tagged_bills/<tag>/<sortby>')
def taggededbills(tag, sortby="status"):
    if not tag:
        return redirect(url_for('bills', sortby=sortby))

    values = request.values.to_dict()
    set_session_by_request_values(values)

    bill_list = Bill.query.filter_by(year=session["yearcode"]).all()
    tagged, untagged = group_bills_by_tag(bill_list, tag)
    bill_table = html_bill_table(tagged, sortby=sortby)

    return render_template('bills.html', title='Bills tagged "%s"' % tag,
                           bill_table=bill_table, tag=tag,
                           sortby=sortby, sortnames=sortnames,
                       leg_session=LegSession.by_yearcode(session["yearcode"]))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('bills'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or urlsplit(next_page).netloc != '':
            next_page = url_for('bills')
        return redirect(next_page)
    return render_template('login.html', title='Sign In', form=form)


@app.route('/logout')
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
@app.route('/newaccount', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('bills'))

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


@app.route('/confirm_email/<auth>')
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


@app.route('/about')
def about():
    return render_template('about.html', title='About NMBillTracker')


@app.route('/help')
def help():
    return render_template('help.html', title='Help for the NMBillTracker')


@app.route('/links')
def links():
    return render_template('links.html', title='Links for NM Bill Tracking')


@app.route('/addbills', methods=['GET', 'POST'])
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
                    print("YIKES! addbills created a duplicate bill", billno,
                          file=sys.stderr)
                    for b in bs:
                        print("   addbills dup", b, file=sys.stderr)
            else:
                if not BILLNO_PAT.match(billno):
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
@app.route('/track_untrack', methods=['GET', 'POST'])
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

        # print("Will track", track_bills, file=sys.stderr)
        # print("Will untrack", untrack_bills, file=sys.stderr)

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
        # since the user expects to see the new bills.
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

            # Now fill them in from the accdb.
            # But sadly, that's not a good idea for new bills,
            # because there's too much information missing from the accdb.
            # print("Updating", new_bills, "from the accdb", sys.stderr)
            # accdb.update_bills(new_bills)

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
                    print("   track_untrack dup", b, file=sys.stderr)

    return redirect(url_for(returnpage))


# XXX Tried to allow specifying year (preferably optionally), but keep getting
# werkzeug.routing.BuildError: Could not build url for endpoint 'popular'. Did you forget to specify values ['year']?
# when visiting http://127.0.0.1:5000/popular/2020.
# @app.route('/popular/<yearcode>')

@app.route('/popular')
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


@app.route('/allbills')
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
    # But hopefully it's been updated recently by the systemd script,
    # so the user won't have to wait for it.
    try:
        allbills = nmlegisbill.all_bills(leg_session.id, yearcode)
        # allbills has the schema documented in nmlegis.g_allbills.

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

    # The lists to pass to the HTML page
    newbills = []
    oldbills = []
    unseen = []

    today = date.today()

    # allbills.html expects a list of dictionaries with keys:
    # [ [billno, title, link, fulltext_link, tracked_by_user ] ]
    # and might also have other items, like num_tracking, amended,
    # comm_sub_links, etc.
    for billno in allbills:
        if billno.startswith("_"):
            # Skip entries like _updated and _schema
            continue

        # Prepare the structure expected by allbills.html
        args = { "billno": billno,
                 "title": allbills[billno].get("title", ""),
                 "url": allbills[billno].get("url", ""),
                 "contentsurl": allbills[billno].get("contents", ""),
                 "user_tracking": billno in bills_tracking
               }
        if "Amendments_In_Context" in allbills[billno]:
            args["amended"] = allbills[billno]["Amendments_In_Context"]
        elif "Floor_Amendments" in allbills[billno]:
            args["amended"] = allbills[billno]["Floor_Amendments"]
        elif 'comm_sub_links' in allbills[billno]:
            # comm_sub_links is a list of [(link, date)]
            # XXX which probably all the amendment types should be
            lastsub = max(allbills[billno]["comm_sub_links"], key=lambda x: x[1])
            args["amended"] = lastsub[0]
            args["amended_date"] = lastsub[1]
        elif "amend" in allbills[billno] and allbills[billno]["amend"]:
            args["amended"] = allbills[billno]["amend"][-1]

        if "overview" in allbills[billno]:
            args["overview"] = allbills[billno]["overview"]

        if user and billno not in bills_seen:
            unseen.append(args)
        elif "history" in allbills[billno] and allbills[billno]["history"]:
            lasthist = allbills[billno]["history"][-1]
            try:
                lastmod = datetime.strptime(lasthist[0], "%Y-%m-%d").date()
                # print(billno, "lastmod:", lastmod, "diff", today - lastmod)
                if (today - lastmod <= timedelta(days=DAYS_CONSIDERED_NEW)
                    and lasthist[1] != "dummyfiled"):
                    newbills.append(args)

                    # Handle title changes
                    if lasthist[1] == "titlechanged" and \
                       len(allbills[billno]["history"]) > 1:
                        oldtitle = allbills[billno]["history"][-2][2]
                        args["oldtitle"] = oldtitle
                else:
                    oldbills.append(args)
            except Exception as e:
                print("** Can't parse date in first element of", lasthist,
                      file=sys.stderr)
                oldbills.append(args)
        else:
            # print("No history in", billno)
            oldbills.append(args)

    # Update user's bills seen, so they won't show up as new next time.
    if user:
        user.update_bills_seen(','.join([ b for b in allbills.keys()
                                          if not b.startswith('_')]),
                               yearcode)

    # Now sort both dicts; the allbills page will display the order
    # passed in, in each case.
    def dic_to_key(dic):
        match = re.match(BILLNO_PAT, dic["billno"])
        if not match:
            return "X" + billno
        billtype, zeros, num = match.groups()
        return billtype + num.zfill(5)

    newbills.sort(key=dic_to_key)
    oldbills.sort(key=dic_to_key)
    unseen.sort(key=dic_to_key)

    bill_lists = [ { 'thelist': unseen,
                     'header': """<h2>Bills You Haven't Seen Before:</h2>
<p>
These are the new or changed bills since the last time you checked this page.
<br />
(Warning: that means that if you leave this page and load it again later,
or reload the page, these bills will no longer be listed as new.)""",
                     'alt': "Nothing new since you last looked."
                   },
                  { 'thelist': newbills,
                    'header': """<h2>Recent Bills:</h2>
<p>
These are bills filed or changed in the past few days""",
                    'alt': "Nothing changed recently."
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


@app.route("/tags", defaults={'tag': None}, methods=['GET', 'POST'])
@app.route("/tags/<tag>", methods=['GET', 'POST'])
def tags(tag=None, sort=None):
    values = request.values.to_dict()
    set_session_by_request_values()

    form = NewTagsForm()
    # Only used for entering a new tag;
    # changing tags on bills uses a second form that isn't a WTF

    bill_list = Bill.query.filter_by(year=session["yearcode"]).all()
    bill_list.sort()

    new_tags = []

    badtag = None
    something_changed = False

    # For the flash messages at the end: these will be tagname: [billnos]
    bills_with_added_tags = defaultdict(list)
    bills_with_removed_tags = defaultdict(list)
    now_tracking = []
    no_longer_tracking = []

    # Was this a form submittal?
    # The form has two submit buttons, with names "submitnewtag" for
    # the new tag input field and "update" to update the buttons for
    # the current tag. Figure out which path the user followed:
    if current_user and not current_user.is_anonymous:
        if 'submit' in values and values['submit'] == 'Create a new tag' \
           and form.validate_on_submit() \
           and 'newtagname' in values and values['newtagname']:
                tag = values["newtagname"]
                new_tags = [tag]

                flash("Now choose some bills to tag with new tag '%s'"
                      % tag)
                print(current_user, "suggested tag '%s'" % tag,
                      file=sys.stderr)

        elif "update" in values:
            checkedboxes = {}
            followchecks = []
            for val in values:
                if val.startswith("f_"):
                    billno = val[2:]
                    followchecks.append(billno)
                elif val.endswith("-name"):
                    billno, tagname, dummy = val.split('-')
                    if billno not in checkedboxes:
                        checkedboxes[billno] = set()
                    checkedboxes[billno].add(tagname)

            # Should be empty, there are currently no followboxes on this page

            alloldtags = set()
            allnewtags = set()
            was_tracking = set([ b.billno
                                 for b in current_user.bills_by_yearcode(
                                         session["yearcode"]) ])

            for bill in bill_list:
                if bill.tags:
                    billtags = set(bill.tags.split(','))
                    alloldtags |= billtags
                else:
                    billtags = set()

                # Are any boxes checked?
                if bill.billno in checkedboxes:
                    if checkedboxes[bill.billno] != billtags:
                        add_tags = checkedboxes[bill.billno] - billtags
                        remove_tags = billtags - checkedboxes[bill.billno]
                        bill.tags = ','.join(sorted(checkedboxes[bill.billno]))
                        db.session.add(bill)
                        something_changed = True

                        for t in add_tags:
                            bills_with_added_tags[t].append(bill.billno)
                        for t in remove_tags:
                            bills_with_removed_tags[t].append(bill.billno)

                    # Make sure all the checked tags are in allnewtags
                    for t in checkedboxes[bill.billno]:
                        allnewtags |= checkedboxes[bill.billno]

                elif bill.tags:  # bill *had* tags but all boxes now unchecked
                    print(current_user, "removed all tags from", bill.billno,
                          file=sys.stderr)
                    remove_tags = billtags
                    for t in remove_tags:
                        bills_with_removed_tags[t].append(bill.billno)
                    bill.tags = ""
                    db.session.add(bill)
                    something_changed = True

                # Also, check to see if any tracking checkboxes changed
                if "f_%s" % bill.billno in values:
                    if bill.billno not in was_tracking:
                        now_tracking.append(bill.billno)
                        current_user.bills.append(bill)

                else:
                    if bill.billno in was_tracking:
                        no_longer_tracking.append(bill.billno)
                        current_user.bills.remove(bill)

            # Any tags removed?
            newtags = allnewtags - alloldtags
            if newtags:    # should be only one
                flash("New tag created: " + ','.join(sorted(list(newtags))))

            for t in bills_with_added_tags:
                msg = "Tagged %s with '%s'" \
                    % (', '.join(bills_with_added_tags[t]), t)
                print(current_user, msg, file=sys.stderr)
                flash(msg)
            for t in bills_with_removed_tags:
                msg = "Un-tagged %s with '%s'" \
                    % (', '.join(bills_with_removed_tags[t]), t)
                print(current_user, msg, file=sys.stderr)
                flash(msg)

            removedtags = alloldtags - allnewtags
            if len(removedtags) == 1:
                msg = "Removed tag " + list(removedtags)[0]
            elif len(removedtags) > 1:
                msg ="Removed tags " + ', '.join(sorted(list(removedtags)))
            else:
                msg = None
            if msg:
                print(current_user, msg, file=sys.stderr)
                flash(msg)

            # The tags list may have to be recalculated
            if newtags or removedtags:
                g_all_tags.pop(session["yearcode"])

            # Tag values have changed. Recompute the all_tags list
            get_all_tags(session["yearcode"])

    # Now any retagging is finished. Group bills according to whether
    # they're tagged with the current tag, if any.
    tagged, untagged = group_bills_by_tag(bill_list, tag)

    if tag:
        bill_lists = {
            "Tagged with '%s'" % tag: tagged,
            "Not %s" % tag: untagged
        }
    else:
        bill_lists = {
            "Bills with tags:": tagged,
            "No tags:": untagged
        }

    def str2color(instr):
        """
        Convert an arbitrary-length string to a CSS style string
        like "background: '#0ff'".
        Return a dictionary, { instr: css_color_code }
        Try to keep them light, so dark text will contrast well.
        If there are commas in the tag string, loop over them.
        If the tag string is "all", return a dictionary of colors
        for all known tags.
        """
        if ',' in instr:
            pieces = instr.split(',')
        elif instr == "all":
            pieces = get_all_tags(session["yearcode"])
        else:
            pieces = [ instr ]

        dic = {}

        for piece in pieces:
            # The hashlib for most tags comes out pretty close in the
            # first few bits; the bits at the other end seem more random.
            sixbytes = hashlib.sha256(piece.encode()).hexdigest()[-6:]
            # hue can be anything between 0 and 1
            h = int(sixbytes[0:2], 16) / 256.
            # lightness between .3 and .55
            l = int(sixbytes[2:4], 16) / 1024 + .3
            # saturation between .5 and 1
            s = int(sixbytes[4:6], 16) / 512 + .5

            rgb = colorsys.hls_to_rgb(h, l, s)

            # rgb = tuple((int((ord(c.lower())-97)*256./26) for c in s[:3]))
            rgb = tuple((int(x * 256) for x in rgb))

            dic[piece] = "#%02x%02x%02x" % rgb
            # print("str2color:", h, l, s, dic)

        return dic

    if now_tracking:
        flash("You are now tracking " + ', '.join(now_tracking))
    if no_longer_tracking:
        flash("You are no longer tracking " + ', '.join(no_longer_tracking))
    if now_tracking or no_longer_tracking:
        db.session.add(current_user)
        something_changed = True

    if something_changed:
        db.session.commit()

    return render_template('tags.html', title="Tags", user=current_user,
                           tag=tag,
                           form=form,
                           yearcode=session["yearcode"],
                           bill_lists=bill_lists,
                           badtag=badtag,
                           colorfcn=str2color,
                           alltags=new_tags+get_all_tags(session["yearcode"]))


# A jinja filter to reformat YYYY-MM-DD votes to something prettier
@app.template_filter()
def prettify_yyyy_mm_dd(yyyymmdd):
    try:
        return datetime.strptime(yyyymmdd, '%Y-%m-%d').strftime('%a, %b %-d, %Y')
    except RuntimeError:
        return yyyymmdd


@app.route("/votes/<billno>")
@app.route("/votes/<billno>/<yearcode>")
def showvotes(billno, yearcode=None):
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    session = LegSession.by_yearcode(yearcode)

    # Make tables of committees and legislators by commcode/sponcode
    # that the jinja template can use
    committees = {}      # commcode -> Committee object
    legislators = {}     # sponcode -> Legislator object

    votes_by_comm = nmlegisbill.get_bill_vote_reports(billno, yearcode,
                                                LegSession.current_yearcode())

    # Make sure it's iterable, even if empty
    if not votes_by_comm:
        votes_by_comm = {}

    # Make a list of reports sorted by date.
    # The structure allows for multiple dates per commcode:
    # { commcode: [ { date: date1, ... },
    #               { date: date2, ... }, ] }
    reports_by_date = []
    for commcode in votes_by_comm:
        for report in votes_by_comm[commcode]:
            if not report:
                continue    # There's always a blank report at the beginning
            report['comm'] = commcode
            reports_by_date.append(report)

            # Make sure there's an entry for this committee
            if commcode in committees:
                continue
            if commcode == 'H':
                comm = Committee.query.filter_by(code='House').first()
            elif commcode == 'S':
                comm = Committee.query.filter_by(code='Senate').first()
            else:
                comm = Committee.query.filter_by(code=commcode).first()
            if comm:
                committees[commcode] = comm
            else:
                print("**** showvotes: Couldn't find committee", commcode,
                      file=sys.stderr)
    reports_by_date.sort(key=lambda r: r['date'])

    bill = Bill.query.filter_by(billno=billno, year=yearcode).first()

    for report in reports_by_date:
        # Report is a dictionary with keys 'date', 'comm', 'votes'
        # where 'votes' is a dict with e.g. { 'yes': [sponcodelist] }

        for votetype in report["votes"]:
            if votetype not in [ 'no', 'yes', 'absent', 'excused' ]:
                # There are other entries, like "rollcall"
                # which points to a URL, not a list of sponcodes.
                continue
            for sponcode in report["votes"][votetype]:
                if sponcode in legislators:
                    continue
                leg = Legislator.query.filter_by(sponcode=sponcode).first()
                if leg:
                    legislators[sponcode] = leg
                else:
                    print("*** Warning: couldn't find legislator",
                          sponcode, file=sys.stderr)
                    # legislators[sponcode] = "%s (new?)" % sponcode

    return render_template('votes.html', title="Votes for %s" % billno,
                           billno=billno, bill=bill, reports=reports_by_date,
                           committees=committees, legislators=legislators,
                           legsession=session)


@app.route("/history/")
@app.route("/history/<billno>")
@app.route("/history/<billno>/<yearcode>")
@login_required
def showhistory(billno=None, yearcode=None):
    """Show title change history for a bill, or for all bills in a session.
       Can also use "all" to indicate all bills, e.g. /history/all/23
       Currently no UI for it.
    """
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    legsession = LegSession.by_yearcode(yearcode)
    sessionid = legsession.id
    allbillinfo = nmlegisbill.all_bills(sessionid, yearcode)

    ret_html = "<h1>%d %s Session Bill Title History</h1>" % (
        legsession.year, legsession.typename)

    def show_hist_for_billno(billno):
        nonlocal ret_html
        info = allbillinfo[billno]
        history = []
        ret_html += "<h3>%s: %s</h3>" % (billno, info["title"])
        if "history" in info:
            for h in info["history"]:
                if h[1] == "introduced":
                    ret_html += "<p>%s: Introduced as %s" % (h[0], h[2])
                elif h[1] == "titlechanged":
                    ret_html += "<p>%s: Title changed to %s" % (h[0], h[2])
        else:
            ret_html += "<p>No history"

    if billno and billno != "all":
        show_hist_for_billno(billno)

    else:
        for billno in allbillinfo:
            if billno.startswith("_"):
                continue
            show_hist_for_billno(billno)

    return ret_html


@app.route("/config")
@login_required
def config():
    if current_user.email not in ADMINS:
        flash("Sorry, this page is only available to administrators.")
        return render_template('config.html', users=None)

    return render_template('config.html', users=User.query.all())


@app.route("/changesession")
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


@app.route("/settings", methods=['GET', 'POST'])
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


@app.route("/password_reset", methods=['GET', 'POST'])
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


@app.route("/trackers", methods=['GET', 'POST'])
@app.route("/trackers/<whichtracker>", methods=['GET', 'POST'])
@app.route("/trackers/<whichtracker>/<yearcode>", methods=['GET', 'POST'])
def show_trackers(whichtracker=None, yearcode=None):
    if not yearcode:
        yearcode = LegSession.current_yearcode()

    trackingdir = os.path.join(app.root_path, 'static', 'tracking', yearcode)

    if whichtracker:
        # Requested a specific tracker
        # There's apparently no way to get a jinja template to include
        # a static file, so instead, read in the static file and pass
        # it to a general include template.
        with open (os.path.join(trackingdir, whichtracker)) as fp:
            content = fp.read()
            content += '<p>\n<a href="/trackers">All Tracking Sheets</a>'
            return render_template('include.html',
                                   filename=whichtracker,
                                   content=content)

    trackers = []
    try:
        filelist = os.listdir(trackingdir)
    except:
        print("No trackers found", file=sys.stderr)
        filelist = []

    for htmlfile in filelist:
        if not htmlfile.endswith('.html'):
            continue
        trackers.append({ "name": htmlfile[:-5], "filename": htmlfile })

    return render_template('trackers.html', title='Tracking Lists',
                           trackers=trackers, yearcode=yearcode)


