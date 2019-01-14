from flask import render_template, flash, redirect, url_for, request
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse
from app import app, db
from app.forms import LoginForm, RegistrationForm, AddBillsForm
from app.models import User, Bill
from app.bills import nmlegisbill
import datetime
import sys


@app.route('/')
@app.route('/index')
@login_required
def index():
    return render_template('index.html', title='Home')


@app.route('/login', methods=['GET', 'POST'])
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


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

# The mega tutorial called this /register,
# but flask seems to have a problem calling anything /register.
# As long as it's named something else, this works.
# I'm not sure why there are methods defined here,
# nothing's passed to this page.
@app.route('/newaccount', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

# in templates/index.html, {{ url_for(addbills) }} doesn't work. Why not?

@app.route('/addbills', methods=['GET', 'POST'])
@login_required
def addbills():
    form = AddBillsForm()
    if form.validate_on_submit():
        billno = form.billno.data
        print("addbills(): billno =", billno, file=sys.stderr)
        # do stuff with valid form
        # then redirect to "end" the form
        # return redirect(url_for('addbills'))
        bill = Bill.query.filter_by(billno=billno).first()
        if bill:
            print("Woohoo, we already know about bill", billno,
                  file=sys.stderr)
            print(bill, file=sys.stderr)
        else:
            # It's a bill not in the database yet: need to fetch it.
            print("fetching billno =", billno, file=sys.stderr)
            b = nmlegisbill.parse_bill_page(billno,
                                            year=datetime.datetime.now().year,
                                            cache_locally=True)
            print("Keys:", file=sys.stderr)
            for k in b.keys():
                try:
                    print("  ", k, len(b[k]), file=sys.stderr)
                except:
                    print("  ", k, "- no len, type", type(b[k]),
                          file=sys.stderr)
            from pprint import pprint
            pprint(b)

            bill = Bill(**b)

            try:
                db.session.add(bill)
                print("Supposedly added %s to the database" % billno,
                      file=sys.stderr)
            except:
                print("Couldn't add %s to the database" % billno,
                      file=sys.stderr)
                sys.exit(1)

        # Either way, bill should be set to a Bill object now.
        # Add it to the current user:
        user = User.query.filter_by(username=current_user.username).first()
        print("%s's bills are:" % user.username, user.bills)
        user.bills.append(bill)
        db.session.add(user)
        print("Supposedly updated user")

        db.session.commit()

        # Clear the form field
        form.billno.data = ""
    else:
        billno = None

    return render_template('addbills.html', title='Add More Bills', form=form,
                           billno=billno)
