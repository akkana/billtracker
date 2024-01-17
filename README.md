# billtracker

## New Mexico Bill Tracker

Track bills as they move through the New Mexico legislature's website,
by scraping the nmlegis.gov website. Send alerts when a bill's status
changes, e.g. when it moves to a new committee so it might be time
to go to a hearing or write letters to committee members.

The project name isn't specific to New Mexico since most of the code
could be extended to any state or venue that offers bill information
online. I'd welcome contributions from other states or, especially,
for federal bills.


## Requirements

In addition to basic flask, this requires:
flask-login sqlalchemy flask-migrate flask-wtf Flask-Mail dateutil xlrd

On a Debian-like system, try:
```
sudo apt install python3-flask-sqlalchemy python3-flask \
                 python3-flask-migrate python3-flask-login \
                 python3-flaskext.wtf python3-flask-mail \
                 python3-dateutil python3-xlrd
```
(or the Python 2 equivalents, if you insist, but that isn't well tested).

Most of those packages should be available.
Some Debian systems may not have python3-flask-mail.


## Running Locally

Run the test server locally like this:

```
export FLASK_APP=run_billtracker.py
flask run
```

When you're satisfied, use whatever production wsgi server you prefer.
The FlaskNotes file in this directory has some notes I made while
setting up WSGI on Apache2.

If you do use Apache2, note that apache2 by default uses the ascii encoding.
If you're sure you're using a specific encoding, like UTF-8, everywhere,
you can use AddDefaultCharset to change apache2's default
https://httpd.apache.org/docs/2.2/en/mod/core.html#adddefaultcharset
(on Debian, a good place to put this is /etc/apache2/conf-enabled/charset.conf).
Or if you have multiple sites configured in apache2 and only want UTF-8
for one flask app, edit the sites-enabled file and add
locale='C.UTF-8'
to the WSGIDaemonProcess line.
Or it might work to edit /etc/apache2/envvars and uncomment the
```
. /etc/default/locale
```
line.


## Unit Tests

There are a few unit tests in the tests/ directory. Run them with:
```
python3 -m unittest discover
```
