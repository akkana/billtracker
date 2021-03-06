"""Get rid of the index for user email, which was causing problems
   because it seemed to imply email was unique,
   which doesn't work for an optional field.
   Untested because the actual server had index names like
   "idx_16615_ix_user_email" for reasons no one seems to know.

Revision ID: f34de039b188
Revises: 3b44ded5afb3
Create Date: 2020-02-03 14:59:40.664757

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f34de039b188'
down_revision = '3b44ded5afb3'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_email')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.create_index('ix_user_email', ['email'], unique=1)

    # ### end Alembic commands ###
