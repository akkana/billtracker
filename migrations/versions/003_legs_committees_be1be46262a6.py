"""legs committees

Revision ID: be1be46262a6
Revises: 657ce93b2db0
Create Date: 2019-01-27 13:08:30.578801

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'be1be46262a6'
down_revision = '657ce93b2db0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('legislator',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sponcode', sa.String(length=9), nullable=True),
    sa.Column('lastname', sa.String(length=25), nullable=True),
    sa.Column('firstname', sa.String(length=25), nullable=True),
    sa.Column('initial', sa.String(length=5), nullable=True),
    sa.Column('title', sa.String(length=50), nullable=True),
    sa.Column('street', sa.String(length=50), nullable=True),
    sa.Column('city', sa.String(length=20), nullable=True),
    sa.Column('state', sa.String(length=2), nullable=True),
    sa.Column('zip', sa.String(length=10), nullable=True),
    sa.Column('work_phone', sa.String(length=25), nullable=True),
    sa.Column('home_phone', sa.String(length=25), nullable=True),
    sa.Column('office_phone', sa.String(length=25), nullable=True),
    sa.Column('email', sa.String(length=50), nullable=True),
    sa.Column('office', sa.String(length=8), nullable=True),
    sa.Column('chairships', sa.String(length=25), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('committee',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=8), nullable=True),
    sa.Column('last_check', sa.DateTime(), nullable=True),
    sa.Column('name', sa.String(length=80), nullable=True),
    sa.Column('mtg_time', sa.String(length=100), nullable=True),
    sa.Column('update_date', sa.DateTime(), nullable=True),
    sa.Column('chair', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['chair'], ['legislator.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('committee_members',
    sa.Column('legislator_id', sa.Integer(), nullable=False),
    sa.Column('committee_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['committee_id'], ['committee.id'], ),
    sa.ForeignKeyConstraint(['legislator_id'], ['legislator.id'], ),
    sa.PrimaryKeyConstraint('legislator_id', 'committee_id')
    )
    with op.batch_alter_table('bill', schema=None) as batch_op:
        batch_op.add_column(sa.Column('location', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('scheduled_date', sa.DateTime(), nullable=True))
        batch_op.drop_column('curloc')
        batch_op.drop_column('curloclink')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('legislators', sa.String(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('legislators')

    with op.batch_alter_table('bill', schema=None) as batch_op:
        batch_op.add_column(sa.Column('curloclink', sa.VARCHAR(length=150), nullable=True))
        batch_op.add_column(sa.Column('curloc', sa.VARCHAR(length=20), nullable=True))
        batch_op.drop_column('scheduled_date')
        batch_op.drop_column('location')

    op.drop_table('committee_members')
    op.drop_table('committee')
    op.drop_table('legislator')
    # ### end Alembic commands ###