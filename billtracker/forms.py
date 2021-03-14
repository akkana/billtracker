from flask_login import current_user

try:
    from flask_wtf import FlaskForm
except:
    from flask_wtf import Form as FlaskForm

from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import ValidationError, DataRequired, Email, \
    EqualTo, Optional
from billtracker.models import User


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[Optional(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    password2 = PasswordField('Repeat Password',
                              validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            print("Someone tried to re-use email", username.data,
                  file=sys.stderr)
            raise ValidationError('Please use a different username.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            print("Someone tried to re-use email", email.data,
                  file=sys.stderr)
            raise ValidationError('That email address is already in use.')

class AddBillsForm(FlaskForm):
    billno = StringField('Bill Designation (e.g. SB21)',
                          validators=[DataRequired()])
    submit = SubmitField('Track Bills')
    billhelp = "Tip: You can enter multiple bill numbers" \
        " separated by commas, e.g. SB21, HR17"

    def validate_billno(self, billno):
        designation = billno.data
        designation = designation.upper()
        if designation[0] not in ['S', 'H', 'J']:
            raise ValidationError('Bills should start with S, H or J.')

        billno.data = designation


class UserSettingsForm(FlaskForm):
    email = StringField('Email', validators=[Optional(), Email()])
    password = PasswordField('New Password')
    password2 = PasswordField('Repeat New Password',
                              validators=[EqualTo('password')])
    submit = SubmitField('Update Settings')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None and user.username != current_user.username:
            raise ValidationError('That email address is already in use.')

class PasswordResetForm(FlaskForm):
    username = StringField('Email', validators=[DataRequired()])
    submit = SubmitField('Send Password Reset')
