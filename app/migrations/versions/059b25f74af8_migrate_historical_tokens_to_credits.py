"""migrate_historical_tokens_to_credits

Revision ID: 059b25f74af8
Revises: 7fadffd3c7d1
Create Date: 2026-07-13 11:35:06.941784

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '059b25f74af8'
down_revision: Union[str, Sequence[str], None] = '7fadffd3c7d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update credits_used for 'chat' operations using gpt-4o-mini pricing
    # Input: $0.00015 / 1k, Output: $0.00060 / 1k. Credit value: $0.01
    op.execute(
        """
        UPDATE credit_usage
        SET credits_used = CEIL(
            (
                ( (cost_breakdown->>'input_tokens')::numeric / 1000.0 * 0.00015 ) + 
                ( (cost_breakdown->>'output_tokens')::numeric / 1000.0 * 0.00060 )
            ) / 0.01
        )
        WHERE cost_breakdown->>'pricing_version' IS NULL 
        AND operation_type = 'chat'
        """
    )
    
    # 2. Update credits_used for any other operations (e.g. embeddings) using text-embedding-3-small pricing
    # Input: $0.00002 / 1k. Credit value: $0.01
    op.execute(
        """
        UPDATE credit_usage
        SET credits_used = CEIL(
            (
                ( (cost_breakdown->>'input_tokens')::numeric / 1000.0 * 0.00002 )
            ) / 0.01
        )
        WHERE cost_breakdown->>'pricing_version' IS NULL 
        AND operation_type != 'chat'
        """
    )

    # 3. Rebuild organizations.credit_balance to reflect the new credit values
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
    # Downgrade reverts `credits_used` back to the raw `total_tokens` inside `cost_breakdown`
    # for the historical rows that we touched.
    op.execute(
        """
        UPDATE credit_usage
        SET credits_used = (cost_breakdown->>'total_tokens')::numeric
        WHERE cost_breakdown->>'pricing_version' IS NULL
        """
    )
    
    # Rebuild organizations.credit_balance based on raw tokens
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
