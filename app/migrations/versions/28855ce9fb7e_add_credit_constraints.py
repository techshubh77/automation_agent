"""add_credit_constraints

Revision ID: 28855ce9fb7e
Revises: e8720a355408
Create Date: 2026-07-13 12:38:23.186748

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28855ce9fb7e'
down_revision: Union[str, Sequence[str], None] = 'e8720a355408'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Prevent negative credit balances at the database level.
    # This is the last line of defense — application code should enforce this first
    # (HTTP 402), but the DB constraint prevents any code path from accidentally
    # going negative (e.g. a bug, direct DB query, or concurrent deduction race).
    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT chk_credit_balance_non_negative "
        "CHECK (credit_balance >= 0)"
    )

    # 2. Convert CreditUsage.status from open String to a constrained PostgreSQL ENUM.
    # This prevents typos like "complted" or "DONE" from corrupting the audit log.
    op.execute("CREATE TYPE credit_usage_status AS ENUM ('pending', 'completed', 'failed', 'refunded')")
    op.execute(
        "ALTER TABLE credit_usage "
        "ALTER COLUMN status TYPE credit_usage_status "
        "USING status::credit_usage_status"
    )


def downgrade() -> None:
    # Convert status back to String
    op.execute(
        "ALTER TABLE credit_usage "
        "ALTER COLUMN status TYPE varchar "
        "USING status::varchar"
    )
    op.execute("DROP TYPE credit_usage_status")

    # Drop CHECK constraint
    op.execute(
        "ALTER TABLE organizations DROP CONSTRAINT chk_credit_balance_non_negative"
    )
