#!/usr/bin/env python3

from tests import setup_flask

from app import initialize_flask_session, clear_flask_session

initialize_flask_session()

from app import app, db
from app.models import Bill
from app.bills import billrequests, accdb

import shutil
import os

# import sys
# print("test_accdb: sys.modules =", sys.modules)

STORED_ACCDBLOC = "test/files/LegInfo-24-01-24T14.accdb"
ACCDBLOC = "test/cache/LegInfo.accdb"
LEGISLOC = "test/cache/Legislation.json"


def test_accdb():
    # Make sure the json file is there
    assert os.path.exists(STORED_ACCDBLOC)

    try:
        os.unlink(ACCDBLOC)
    except FileNotFoundError:
        pass
    try:
        os.unlink(LEGISLOC)
    except FileNotFoundError:
        pass
    shutil.copyfile(STORED_ACCDBLOC, ACCDBLOC)
    print("Copied to", ACCDBLOC)
    accdb.cache_bill_table(ACCDBLOC, LEGISLOC)

    with app.test_client() as test_client:
        with app.app_context():

            db.create_all()
            print("At the beginning, allbills:", Bill.query.all())

            # response = test_client.get('/')
            # # The test app gives 302, not 200 for this
            # assert response.status_code == 200 or response.status_code == 302
            # assert "OK" in response.text
            # print("Response data:", response.text)

            with test_client.session_transaction() as session:
                session["yearcode"] = '24'

            # Add a couple of empty bills
            hjr7 = Bill()
            hjr7.billno = 'HJR7'
            sb43 = Bill()
            sb43.billno = 'SB43'

            accdb.update_bills([hjr7, sb43])

            db.session.add(hjr7)
            db.session.add(sb43)
            db.session.commit()

            allbills = Bill.query.all()
            print("Allbills:", allbills)
            assert len(allbills) == 2

            hjr7 = Bill.query.filter_by(billno="HJR7").first()
            print(hjr7)
            assert hjr7.billno == "HJR7"
            assert hjr7.title == "COMMISSION ON LEGISLATIVE SALARIES, CA"
            print("statustext:", hjr7.statustext)

            # assert hjr7.statustext == \
            #                  "Legislative Day: 2, Calendar Day: 01/22/2024, "
            #                  "Sent to HGEIC - Referrals: HGEIC/HJC")

    os.unlink(ACCDBLOC)
    os.unlink(LEGISLOC)

    print("******** Calling clear_flask_session() from test_accdb")
    clear_flask_session()
