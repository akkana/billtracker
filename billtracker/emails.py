
from flask_mail import Message
from billtracker import billtracker, mail

from flask import render_template
from config import ADMINS

from threading import Thread


def send_async_email(billtracker, msg):
    with billtracker.app_context():
        mail.send(msg)


def send_email(subject, sender, recipients, text_body, html_body=None):
    """Send one email to a list of recipients
    """
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    if html_body:
        msg.html = html_body
    thr = Thread(target=send_async_email, args=[billtracker, msg])
    thr.start()


def daily_user_email(recipient):
    '''Given a user object, send daily mail to that user.
    '''
    if not recipient.email:
        return

    # Get the list of bills, sorted by status
    bills = recipient.bills_by_yearcode(sort_type="status")

    send_email("NM Bill Tracker Daily Update",
               "noreply@nmbilltracker.com", [ recipient.email ],
               render_template("bill_email.txt",
                               recipient=recipient, bill_list=bills),
               render_template("bill_email.html",
                               recipient=recipient, bill_list=bills))
