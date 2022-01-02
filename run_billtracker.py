import os

# If you want a site-wide alert or news message, set the environment
# variables BILLTRACKER_INFO or BILLTRACKER_ALERT.
# You can set them here, or in your WSGI script
# or however you run the app.
# But be sure to set them at the beginning of the script,
# before you import anything from billtracker.
# os.environ["BILLTRACKER_INFO"] = "The next session will start on Jan 6"
# os.environ["BILLTRACKER_ALERT"] = "Some important alert"

from billtracker import billtracker, db
from billtracker.models import User, Bill

@billtracker.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'Bill': Bill}
