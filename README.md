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

In addition to flask, on Debian this requires:
apt-get install python3-flask-login python3-flask-sqlalchemy python3-flask-migrate python3-dateutil

Then either:
apt-get install python3-wtforms
or
pip3 install python-wtf

The latter, unfortunately, is required on Debian because of
[Bug 912069](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=912069):
watch [the Debian excuse page](https://qa.debian.org/excuses.php?package=flask-wtf) for updates.

I created a python3 venv:
python3 -m venv --system-site-packages python3-venv

Enabled it:
source python3-venv/bin/activate

Installed wtf:
pip3 install python-wtf
pip3 install Flask-WTF

Then inserted the relevant path into the .wsgi file apache will use:
sys.path.insert(0, '/path/to/python3-venv/lib/python3.5/site-packages/')
