#!/usr/bin/env python3

# Regularly update various parts of the BillTracker database.

# Things this script can do:
# Send daily emails (once a day)
# Update legislators list (once a day)
# Update amendments, FIR, LESC (every few hours)
# Update bills (every few hours)

import os
import requests


#############################################################
# CONFIGURATION: YOU MUST EDIT THESE or use environment vars.
#############################################################
# Set the secret key here:
KEY = os.environ.get('SECRET_KEY') or 'MY_SECRET_KEY'

# Set the base URL for your billtracker installation:
BASEURL = os.environ.get('BILLTRACKER_HOME') or 'https://yourdomain'


#############################################################
# Optional configuration: use the defaults, or change them.

# Is the legislature currently in session?
# Only send daily emails if it is.
in_session = True

# Log file
LOGFILE = '/var/log/billtracker-update.log'

# Times for various services:
if in_session:
    email_hours = [ 21 ]
    legislator_hours = [ ]    # Should happen automatically when needed
    FIR_hours = [ 2, 13 ]
    LESC_hours = [ 3, 15 ]
    amend_hours = [ 4, 16 ]
    db_backup_hours = [ 1, 13 ]

    # Committees are really the important things to refresh:
    # they're the only way to find out when bills are scheduled,
    # and their schedules are updated randomly and sometimes frequently.
    committee_hours = [ 5, 11, 17, 23 ]

    # Bill updating is a bit more complicated since there are so many bills
    # and we want to avoid flooding the legislative website.
    # But we don't want to wait too long; a lot can happen in 4 hours.
    # So bill_update_percent is the percent of bills to update each hour.
    # The billtracker will update that percent of bills sorted by
    # how long it's been since the last update.
    # Still, no need to keep refreshing throughout the night.
    # bill_hours = list(range(6, 24))
    bill_hours = [ 0, 3, 6, 9, 12, 15, 18, 21 ]
    bill_update_percent = 20

else:
    # When out of session, only update bills and back up the db once a day,
    # and don't update the other tables at all.
    email_hours = [ ]
    legislator_hours = [ ]    # Should happen automatically when needed
    FIR_hours = [ ]
    LESC_hours = [ ]
    amend_hours = [ ]
    db_backup_hours = [ 5 ]
    committee_hours = [ ]

    bill_hours = [ 0, 2, 4 ]
    bill_update_percent = 34

# End configuration, no need to edit anything below this.
#############################################################


from datetime import datetime

def main():
    global BASEURL

    now = datetime.now()

    # Flask is very picky about double slashes
    while BASEURL.endswith('/'):
        BASEURL = BASEURL[:-1]

    responses = {}

    if now.hour in db_backup_hours:
        posturl = '%s/api/db_backup' % (BASEURL)
        postdata = { "KEY": KEY }
        res = requests.post(posturl, postdata)

    if now.hour in committee_hours:
        coms = requests.get('%s/api/all_committees' % (BASEURL)).text
        if not coms.startswith('FAIL'):
            committees = coms.split(',')
            for com in committees:
                print("Fetching committee", com)
                posturl = '%s/api/refresh_committee' % (BASEURL)
                postdata = { "COMCODE": com, "KEY": KEY }
                responses['committee %s' % com] \
                    = requests.post(posturl, postdata)

    # Nothing for legislators, they'll be updated if needed
    # when updating committees.

    # Update the various supporting files.
    # This doesn't pass yearcode, and only refreshes
    # the current legislative session.
    if now.hour in FIR_hours:
        print("Updating FIRs")
        posturl = '%s/api/refresh_legisdata' % (BASEURL)
        postdata = { "TARGET": "FIRlink",
                     "KEY": KEY,
                     "URL": "ftp://www.nmlegis.gov/firs" }
        print("posturl", posturl)
        print("firdata", postdata)
        responses['FIR'] = requests.post(posturl, postdata)

    if now.hour in LESC_hours:
        print("Updating LESCs")
        posturl = '%s/api/refresh_legisdata' % (BASEURL)
        postdata = { "TARGET": "LESClink",
                     "KEY": KEY,
                     "URL": "ftp://www.nmlegis.gov/LESCAnalysis" }
        responses['LESC'] = requests.post(posturl, postdata)

    if now.hour in amend_hours:
        print("Updating amendments")
        posturl = '%s/api/refresh_legisdata' % (BASEURL)
        postdata = { "TARGET": "amendlink",
                     "KEY": KEY,
                     "URL": "ftp://www.nmlegis.gov/Amendments_In_Context" }
        responses['amend'] = requests.post(posturl, postdata)

    if now.hour in bill_hours:
        print("Refreshing the list of sessions")
        responses["sessions"] = requests.post("%s/api/refresh_session_list" \
                                              % BASEURL,
                                              data={ 'KEY': KEY })

        print("Updating some bills")
        billstr = requests.get('%s/api/bills_by_update_date' % (BASEURL)).text
        updated_bills = []
        failed_updates = []
        if not billstr:
            print("No bills to update")
        elif not billstr.startswith("FAIL"):
            allbills = billstr.split(',')
            num2update = len(allbills) * bill_update_percent // 100
            if num2update == 0 and allbills:
                num2update = 1
            print("Will update %d bills" % num2update)
            for billno in allbills[:num2update]:
                posturl = '%s/api/refresh_one_bill' % (BASEURL)
                billdata = { "BILLNO": billno,
                             "KEY": KEY }
                responses[billno] = requests.post(posturl, billdata)

    # Email comes last, in case anything else needed updating.
    if now.hour in email_hours:
        responses['email'] = requests.get('%s/api/all_daily_emails/%s' \
                                          % (BASEURL, KEY))

    if responses:
        for r in responses:
            print(r, ":", responses[r].text)
    else:
        print("Nothing to do at hour", now.hour)

if __name__ == '__main__':
    main()

