"""convert_credits_to_decimal

Revision ID: e8720a355408
Revises: 059b25f74af8
Create Date: 2026-07-13 11:46:25.234299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8720a355408'
down_revision: Union[str, Sequence[str], None] = '059b25f74af8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Alter Column Types
    op.alter_column('organizations', 'credit_balance', type_=sa.Numeric(18, 6), existing_type=sa.BigInteger(), postgresql_using="credit_balance::numeric")
    op.alter_column('credit_usage', 'credits_used', type_=sa.Numeric(18, 6), existing_type=sa.BigInteger(), postgresql_using="credits_used::numeric")

    # 2. Recalculate 'chat' operations
    op.execute(
        """
        UPDATE credit_usage
        SET credits_used = (
            ( (cost_breakdown->>'input_tokens')::numeric / 1000.0 * 0.00015 ) + 
            ( (cost_breakdown->>'output_tokens')::numeric / 1000.0 * 0.00060 )
        ) / 0.01
        WHERE cost_breakdown->>'pricing_version' IS NULL 
        AND operation_type = 'chat'
        """
    )
    
    # 3. Recalculate non-chat operations
    op.execute(
        """
        UPDATE credit_usage
        SET credits_used = (
            ( (cost_breakdown->>'input_tokens')::numeric / 1000.0 * 0.00002 )
        ) / 0.01
        WHERE cost_breakdown->>'pricing_version' IS NULL 
        AND operation_type != 'chat'
        """
    )

    # 4. Rebuild organizations.credit_balance to reflect exact decimals
    op.execute(
        """
        WITH calculated_balances AS (
            SELECT organization_id, COALESCE(SUM(credits_used), 0) as total_used
            FROM credit_usage
            GROUP BY organization_id
        )
        UPDATE organizations o
        SET credit_balance = 0 - cb.total_used
        FROM calculated_balances cb
        WHERE o.org_id = cb.organization_id;
        """
    )


def downgrade() -> None:
    op.alter_column('credit_usage', 'credits_used', type_=sa.BigInteger(), existing_type=sa.Numeric(18, 6), postgresql_using="CEIL(credits_used)")
    op.alter_column('organizations', 'credit_balance', type_=sa.BigInteger(), existing_type=sa.Numeric(18, 6), postgresql_using="CEIL(credit_balance)")
