
from flask_mail import Message
from app import mail

from flask import render_template
from config import ADMINS

def send_email(subject, sender, recipients, text_body, html_body):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    mail.send(msg)

def daily_bill_email(recipient):
    if not recipient.email:
        return
    send_email("NM Bill Tracker Daily Update",
               "noreply@nmbilltracker.com", [ recipient.email ],
               render_template("bill_email.txt", recipient=recipient),
               render_template("bill_email.html", recipient=recipient))

