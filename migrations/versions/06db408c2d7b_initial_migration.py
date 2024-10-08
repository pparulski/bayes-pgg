"""Initial migration

Revision ID: 06db408c2d7b
Revises: 
Create Date: 2024-09-23 04:34:38.482973

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '06db408c2d7b'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('participant',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('participant_id', sa.String(length=16), nullable=False),
    sa.Column('prolific_pid', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('group', sa.String(length=50), nullable=False),
    sa.Column('session_num', sa.Integer(), nullable=False),
    sa.Column('round_num', sa.Integer(), nullable=False),
    sa.Column('contribution', sa.Integer(), nullable=False),
    sa.Column('bot_contribution', sa.Integer(), nullable=False),
    sa.Column('participant_balance', sa.Float(), nullable=False),
    sa.Column('bot_balance', sa.Float(), nullable=False),
    sa.Column('net_gain', sa.Float(), nullable=False),
    sa.Column('start_timestamp', sa.DateTime(), nullable=True),
    sa.Column('end_timestamp', sa.DateTime(), nullable=True),
    sa.Column('bonus', sa.Float(), nullable=True),
    sa.Column('incom_1', sa.Integer(), nullable=True),
    sa.Column('incom_2', sa.Integer(), nullable=True),
    sa.Column('incom_3', sa.Integer(), nullable=True),
    sa.Column('incom_4', sa.Integer(), nullable=True),
    sa.Column('incom_5', sa.Integer(), nullable=True),
    sa.Column('incom_6', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('participant_id', 'session_num', 'round_num', name='_participant_session_round_uc')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('participant')
    # ### end Alembic commands ###
