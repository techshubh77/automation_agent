"""reorder columns

Revision ID: 7fadffd3c7d1
Revises: 02d2648de241
Create Date: 2026-07-10 19:16:49.887714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7fadffd3c7d1'
down_revision: Union[str, Sequence[str], None] = '02d2648de241'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # We rename the columns that come AFTER where we want credit_balance to be.
    op.execute("ALTER TABLE organizations RENAME COLUMN is_active TO is_active_old")
    op.execute("ALTER TABLE organizations RENAME COLUMN created_at TO created_at_old")
    op.execute("ALTER TABLE organizations RENAME COLUMN updated_at TO updated_at_old")

    # Recreate them at the end of the table
    op.add_column('organizations', sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=True))
    op.add_column('organizations', sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.add_column('organizations', sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True))

    # Copy the data over
    op.execute('''
        UPDATE organizations SET 
            is_active = is_active_old, 
            created_at = created_at_old, 
            updated_at = updated_at_old
    ''')

    # Make them non-nullable now that data is populated
    op.alter_column('organizations', 'is_active', nullable=False)
    op.alter_column('organizations', 'created_at', nullable=False)
    op.alter_column('organizations', 'updated_at', nullable=False)

    # Drop the old columns
    op.drop_column('organizations', 'is_active_old')
    op.drop_column('organizations', 'created_at_old')
    op.drop_column('organizations', 'updated_at_old')


def downgrade() -> None:
    # Revert by doing the exact same trick, pushing credit_balance to the end
    op.execute("ALTER TABLE organizations RENAME COLUMN credit_balance TO credit_balance_old")
    op.add_column('organizations', sa.Column('credit_balance', sa.BigInteger(), nullable=True))
    op.execute("UPDATE organizations SET credit_balance = credit_balance_old")
    op.alter_column('organizations', 'credit_balance', nullable=False)
    op.drop_column('organizations', 'credit_balance_old')
