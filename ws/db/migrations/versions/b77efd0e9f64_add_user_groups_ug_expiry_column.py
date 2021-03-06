"""add user_groups.ug_expiry column

Revision ID: b77efd0e9f64
Revises: 53c1e2e65d94
Create Date: 2018-09-22 11:48:46.437771

"""
from alembic import op
import sqlalchemy as sa

# add our project root into the path so that we can import the "ws" module
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../.."))

import ws.db.sql_types



# revision identifiers, used by Alembic.
revision = 'b77efd0e9f64'
down_revision = '53c1e2e65d94'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user_groups', sa.Column('ug_expiry', ws.db.sql_types.MWTimestamp(), nullable=True))
    op.create_index('ug_expiry', 'user_groups', ['ug_expiry'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ug_expiry', table_name='user_groups')
    op.drop_column('user_groups', 'ug_expiry')
    # ### end Alembic commands ###
