from billtracker import billtracker, db
from billtracker.models import User, Bill

@billtracker.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'Bill': Bill}
