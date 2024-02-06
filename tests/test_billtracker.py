#!/usr/bin/env python3

"""Test the functioning of the billtracker flask app and its
   underlying database.
"""

from tests import setup_flask
from app import initialize_flask_session, clear_flask_session

initialize_flask_session()

# Now it's safe (I hope) to import the flask stuff
from flask import Flask, session
from app import app, db
from app.models import User, Bill, LegSession
from app.bills import billrequests
from app import routes, models, api, mailapi


from config import Config, basedir

KEY = 'TESTING_NOT_SO_SECRET_KEY'
app.config['SQLALCHEMY_DATABASE_URI'] = setup_flask.DATABASE_URL
app.config['TESTING'] = True
app.config['SECRET_KEY'] = KEY

# To help with submitting form data from tests
# -- but form.validate_on_submit still returns False.
app.config['WTF_CSRF_ENABLED'] = False

# Needed for captcha validation
from app.forms import RegistrationForm
from app.routes import initialize_captcha
from app import chattycaptcha

import json
import os


# Some of these tests run flask routes and compare the generated HTML
# against a saved file. That means that whenever anything about the
# page changes, it breaks the tests. If you're sure that the only things
# you changed are chrome and not content, set renew_files to True and
# run the test again. It will generate the files you need to copy into
# the test/files directory to make the tests work.
# Don't forget to set it back to False afterward.
renew_files = False


def test_password_hashing():
    u = User(username='testuser')
    u.set_password('testpassword')
    assert not u.check_password('notthepassword')
    assert u.check_password('testpassword')


def test_billtracker():
    # Uncomment to get verbose information on cache/net requests:
    # billrequests.DEBUG = True

    # Make sure there's no lock file for allbills
    try:
        os.unlink(os.path.join(CACHEDIR, "allbills_19.json.lock"))
    except:
        pass

    with app.test_client() as test_client:
        with app.app_context():
            # Do we also need a app.test_request_context() ?
            # with app.test_request_context():
            # Looks like no.

            db.create_all()
            print("At the beginning, allbills:", Bill.query.all())

            # response = test_client.get('/')
            # # The test app gives 302, not 200 for this
            # assert response.status_code == 200 or response.status_code == 302
            # print("Response data:", response.text)

            with test_client.session_transaction() as session:
                session["yearcode"] = '19'
                response = test_client.post("/api/refresh_session_list",
                                            data={ 'KEY': KEY })
                # assert response.text.startswith('OK')

                # Set up form and session variables that will be
                # used later to create a user.
                # These apparently have to be created inside
                # the original 'with' clause.
                USERNAME = "testuser"
                PASSWORD = "testpassword"
                form = RegistrationForm()
                form.username.data = USERNAME
                form.password.data = PASSWORD
                form.password2.data = PASSWORD

                initialize_captcha()
                session["capq"] = next(iter(chattycaptcha.captcha.QandA))
                capa = chattycaptcha.captcha.QandA[session["capq"]][0]

            # Now exited the "with", so session should now be visible
            # from anywhere.

            # Fetch the list of legislative sessions.
            # Do this first, many things depend on current_leg_session()
            response = test_client.post("/api/refresh_session_list",
                                     data={ 'KEY': KEY })
            assert (response.status_code == 200 or
                    response.status_code == 302)
            assert response.get_data(as_text=True).startswith('OK')
            sessions = LegSession.query.filter_by(yearcode='19').all()
            assert len(sessions) == 1
            assert sessions[0].yearcode == '19'
            assert sessions[0].year == 2019
            assert sessions[0].typename == "Regular"

            assert LegSession.current_yearcode() == '20s2'

            # Check that the home page loads.
            response = test_client.get('/index', follow_redirects=True)
            assert (response.status_code == 200 or
                    response.status_code == 302)

            # Add a new bill, using the already cached page
            response = test_client.post("/api/refresh_one_bill",
                                        data={ 'BILLNO': 'HB73', 'KEY': KEY,
                                               'YEARCODE': '19'} )
            assert (response.status_code == 200 or
                    response.status_code == 302)
            assert response.get_data(as_text=True) == 'OK Updated HB73'

            # There should be exactly one bill in the database now
            allbills = Bill.query.all()
            print("allbills:", allbills)
            assert len(allbills) == 1

            # Test that bills_by_update_date now shows the bill
            response = test_client.post("/api/bills_by_update_date",
                                        data={ 'yearcode': '19' })
            assert response.get_data(as_text=True) == 'HB73'

            # Same thing but with GET
            response = test_client.get("/api/bills_by_update_date?yearcode=19")
            assert response.get_data(as_text=True) == 'HB73'

            # Test whether the bill just added is in the database
            bill = Bill.query.filter_by(billno="HB73").first()
            assert bill.billno == "HB73"
            assert bill.title == 'EXEMPT NM FROM DAYLIGHT SAVINGS TIME'

            # Add a bill that has mostly null fields.
            bill = Bill()
            billdata = {
                'billno': 'HB100',
                'chamber': 'H',
                'billtype': 'B',
                'number': '100',
                'year': '19',
                'title': 'BILL WITH NULL STUFF',
                'sponsor': None,
                'sponsorlink': None,
                'contentslink': None,
                'amendlink': None,
                'last_action_date': None,
                'statusHTML': None,
                'statustext': None,
                'FIRlink': None,
                'LESClink': None,
                'update_date': None,
                'mod_date': None
            }
            bill.set_from_parsed_page(billdata)
            db.session.add(bill)
            db.session.commit()

            # Needed to test WTForms to test any POSTs:
            app.config['WTF_CSRF_ENABLED'] = False

            response = test_client.post("/newaccount",
                                     data={ 'username': USERNAME,
                                            'password': PASSWORD,
                                            'password2': PASSWORD,
                                            'capq': session["capq"],
                                            'capa' : capa,
                                            'submit': 'Register' })
            assert (response.status_code == 200 or
                    response.status_code == 302)
            allusers = User.query.all()
            assert len(allusers) == 1
            user = User.query.filter_by(username='testuser').first()
            assert user.username == 'testuser'

            # Try addbills without being logged in:
            response = test_client.post('/addbills',
                                        data={ 'billno':   'HB73',
                                               'yearcode': '19',
                                               'submit':   'Track a Bill'})
            assert (response.status_code == 200 or
                    response.status_code == 302)
            assert response.headers['location'] == '/login'
                             # 2022 change: this used to be the location:
                             # 'http://localhost/login')

            # Now log in
            response = test_client.post('/login', data=dict(
                username=USERNAME,
                password=PASSWORD
            ), follow_redirects=True)
            assert (response.status_code == 200 or
                    response.status_code == 302)
            text_response = response.get_data(as_text=True)
            assert "Bills testuser is tracking:" in text_response
            assert "This is your first check" in text_response

            # No email specified, so that warning shouldn't be there
            assert ("Warning: Your email hasn't been confirmed yet"
                    not in text_response)

            # view the index with yearcode 19, to set the yearcode in the session.
            response = test_client.get("/?yearcode=19")
            assert (response.status_code == 200 or
                    response.status_code == 302)

            # Now try addbills again as a logged-in user:
            response = test_client.post('/addbills',
                                        data={ 'billno': 'HB73',
                                               'yearcode': '19',
                                               'submit': 'Track a Bill' })
            assert (response.status_code == 200 or
                    response.status_code == 302)

            response = test_client.post('/addbills',
                                        data={ 'billno': 'HB100',
                                               'yearcode': '19',
                                               'submit': 'Track a Bill' })
            assert (response.status_code == 200 or
                    response.status_code == 302)

            # Need to re-query the user to get the updated bill list (why??):
            user = User.query.filter_by(username='testuser').first()

            assert len(user.bills) == 2
            assert user.bills[0].billno == 'HB73'
            assert user.bills[1].billno == 'HB100'

            # Now test the index page again
            response = test_client.get('/', follow_redirects=True)
            assert (response.status_code == 200 or
                    response.status_code == 302)
            pageHTML = response.get_data(as_text=True)
            assert ('HB73' in pageHTML)
            assert ('HB100' in pageHTML)

            # Make sure untracking works too
            # Failing to re-query user here sometimes results in:
            # sqlalchemy.orm.exc.DetachedInstanceError: Parent instance <User at 0x7f0393d60490> is not bound to a Session; lazy load operation of attribute 'bills' cannot proceed (Background on this error at: http://sqlalche.me/e/13/bhk3)
            user = User.query.filter_by(username='testuser').first()
            bill0, bill1 = user.bills
            user.bills.remove(bill0)
            user.bills.remove(bill1)
            db.session.add(user)
            db.session.commit()
            user = User.query.filter_by(username='testuser').first()
            assert len(user.bills) == 0

            #
            # Test edge case syntaxes users might type into the addbills page,
            # and also make sure incorrect billnumbers aren't added
            # to the database from parse errors
            #
            response = test_client.post('/addbills',
                                        data={ 'billno': "HB-100",
                                               'yearcode': '19',
                                               'submit': 'Track a Bill' })
            assert (response.status_code == 200 or
                    response.status_code == 302)
            pageHTML = response.get_data(as_text=True)
            assert """<span style="color: red;">""" in pageHTML
            assert """look like a bill number""" in pageHTML
            user = User.query.filter_by(username="testuser").first()
            assert len(user.bills) == 0

            allbills = Bill.query.all()
            assert len(allbills) == 2

            response = test_client.post('/addbills',
                                        data={ 'billno': "HB  100 ",
                                               'yearcode': '19',
                                               'submit': 'Track a Bill' })
            assert (response.status_code == 200 or
                    response.status_code == 302)
            pageHTML = response.get_data(as_text=True)
            assert """<span style="color: red;">""" in pageHTML
            assert """look like a bill number""" in pageHTML
            user = User.query.filter_by(username="testuser").first()
            assert len(user.bills) == 0

            # This one should work
            response = test_client.post('/addbills',
                                        data={ 'billno': " HB100",
                                               'yearcode': '19',
                                               'submit': 'Track a Bill' })
            assert (response.status_code == 200 or
                    response.status_code == 302)
            assert ("You are now following HB100"
                    in response.get_data(as_text=True))
            user = User.query.filter_by(username="testuser").first()
            assert len(user.bills)== 1
            allbills = Bill.query.all()
            assert len(allbills) == 2

            allbills = Bill.query.all()
            assert len(allbills) == 2

            # Remove all the user's bills, to start over
            def untrackall():
                # This function apparently doesn't inherit user
                # from the containing function.
                user = User.query.filter_by(username="testuser").first()
                userbills = user.bills
                for b in userbills:
                    user.bills.remove(b)
                db.session.add(user)
                db.session.commit()
                print("user.bills now:", user.bills)

            untrackall()

            user = User.query.filter_by(username="testuser").first()
            print("user.bills now:", user.bills)
            assert len(user.bills) == 0

            # For a request that includes a string with a comma,
            # like "hB73, hb  100  ", the comma will be interpreted as
            # part of JSON, so it needs to be encoded first.
            userstring = "hb0073, hb  100  , hb-45 "
            response = test_client.post('/addbills',
                                        data=json.dumps({
                                            'billno': userstring,
                                            'yearcode': '19',
                                            'submit': 'Track a Bill' }),
                                        content_type='application/json')
            assert (response.status_code == 200 or
                    response.status_code == 302)

            user = User.query.filter_by(username="testuser").first()
            userstring = "hb73, hb100 "
            response = test_client.post('/addbills',
                                        data=json.dumps({
                                            'billno': userstring,
                                            'yearcode': '19',
                                            'submit': 'Track a Bill' }),
                                        content_type='application/json')
            assert (response.status_code == 200 or
                    response.status_code == 302)

            user = User.query.filter_by(username="testuser").first()
            assert len(user.bills) == 2
            userbillnos = [ b.billno for b in user.bills ]
            assert ('HB73' in userbillnos)
            assert ('HB100' in userbillnos)

            # Some bills_seen tests
            billno_list = [ 'SB1', 'SB2', 'SB3' ]
            user.update_bills_seen(','.join(billno_list), '19')
            seen = user.get_bills_seen('19')
            assert seen == billno_list

            user.add_to_bills_seen([ "HB1", "HB100" ], '19')
            billno_list.append("HB1")
            billno_list.append("HB100")
            seen = user.get_bills_seen('19')
            billno_list.sort()
            assert seen == billno_list

            ################
            # Now check how the allbills page influences bills_seen
            user.bills_seen = ""
            db.session.add(user)
            db.session.commit()

            # allbills page: everything should be new.
            response = test_client.get("/allbills?yearcode=19")
            assert (response.status_code == 200 or
                    response.status_code == 302)

            response_html = response.get_data(as_text=True)

            with open("test/files/allnewbills.html") as fp:
                expected_html = fp.read()
            if renew_files:
                if response_html != expected_html:
                    with open("/tmp/allnewbills.html", "w") as outfp:
                        outfp.write(response_html)
                    print("************ allnewbills will fail without: "
                        "cp /tmp/allnewbills.html test/files/allnewbills.html")
            else:
                with open("/tmp/response.html", 'w') as ofp:
                    ofp.write(response_html)
                assert response_html == expected_html

            # Now all the bills have been seen, none should be new.
            response = test_client.get("/allbills?yearcode=19")
            assert (response.status_code == 200 or
                    response.status_code == 302)
            response_html = response.get_data(as_text=True)

            with open("test/files/nonewbills.html") as fp:
                expected_html = fp.read()
            if renew_files:
                if response_html != expected_html:
                    with open("/tmp/nonewbills.html", "w") as outfp:
                        outfp.write(response_html)
                    print("************ nonewbills will fail without: "
                          "cp /tmp/nonewbills.html test/files/nonewbills.html")
            else:
                assert response_html == expected_html

            # The next section requires a lot of substituting of
            # temporary replacement files. A pair of helpers:
            def substitute_file(filename, extra):
                os.rename(filename, filename + ".save")
                os.rename(filename + extra, filename)

            def orig_file(filename, extra):
                os.rename(filename, filename + extra)
                os.rename(filename + ".save", filename)

            # Change a bill's title. That involves moving the bill's
            # html description aside and replacing it with one that
            # has a different title.
            substitute_file("test/cache/Legislation_List_Session=57",
                            ".titlechange")
            substitute_file("test/cache/2019-HB73.html", ".titlechange")

            # Make sure the old title is the expected one
            hb73 = Bill.query.filter_by(billno="HB73").first()
            assert hb73.title == "EXEMPT NM FROM DAYLIGHT SAVINGS TIME"

            # Refresh HB73 so it will get the new title
            # XXX probably remove this!
            response = test_client.post("/api/refresh_one_bill",
                                        data={ 'BILLNO': 'HB73', 'KEY': KEY,
                                               'YEARCODE': '19'} )
            assert (response.status_code == 200 or
                    response.status_code == 302)
            assert response.get_data(as_text=True) == 'OK Updated HB73'

            hb73 = Bill.query.filter_by(billno="HB73").first()
            assert hb73.title == "THIS IS A NEW TITLE FOR THIS BILL"

            # move the files back where they belong.
            orig_file("test/cache/Legislation_List_Session=57",
                      ".titlechange")
            orig_file("test/cache/2019-HB73.html", ".titlechange")

            # Now test the allbills page again to make sure it shows
            # the retitled bill as new.
            response = test_client.get("/allbills?yearcode=19")
            assert (response.status_code == 200 or
                    response.status_code == 302)
            response_html = response.get_data(as_text=True)

    os.unlink(setup_flask.TEST_DB)

    print("******** Calling clear_flask_session() from test_billtracker")
    clear_flask_session()

