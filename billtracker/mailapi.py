#!/usr/bin/env python3

"""BillTracker APIs related to email"""


from billtracker import billtracker, db
from billtracker.models import User
from billtracker.forms import EmailBlastForm
from .emails import daily_user_email, send_email

from flask import render_template

import sys
import traceback
from datetime import datetime, date


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

    # Figure out which users are tracking bills that have changed
    # in the last day:
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
    """Blast an email to all billtracker users with email addresses"""

    if key != billtracker.config["SECRET_KEY"]:
        return "FAIL Bad key\n"

    form = EmailBlastForm()

    if form.validate_on_submit():
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
        subject = form.subject.data
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
