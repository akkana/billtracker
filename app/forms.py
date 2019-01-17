
try:
    from flask_wtf import FlaskForm
except:
    from flask_wtf import Form as FlaskForm

from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import ValidationError, DataRequired, Email, \
    EqualTo, Optional
from app.models import User


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[Optional(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    password2 = PasswordField(
        'Repeat Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Please use a different username.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('Please use a different email address.')

class AddBillsForm(FlaskForm):
    billno = StringField('Bill Designation (e.g. SB01)',
                          validators=[DataRequired()])
    submit = SubmitField('Track a Bill')

    def validate_billno(self, billno):
        designation = billno.data
        print("Should we validate billno", designation, "?")
        designation = designation.upper()
        if designation[0] not in ['S', 'H', 'J']:
            raise ValidationError('Bills should start with S, H or J.')

        print(designation, "validates.")
        billno.data = designation
