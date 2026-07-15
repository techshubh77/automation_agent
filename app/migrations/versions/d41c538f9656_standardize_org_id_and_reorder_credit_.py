"""standardize_org_id_and_reorder_credit_usage

Revision ID: d41c538f9656
Revises: 288e66e87c10
Create Date: 2026-07-14 16:22:01.069063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd41c538f9656'
down_revision: Union[str, Sequence[str], None] = '288e66e87c10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Rename column and index
    op.alter_column('organizations', 'org_id', new_column_name='organization_id')
    op.execute('ALTER INDEX ix_organizations_org_id RENAME TO ix_organizations_organization_id;')

    # 2. Fix credit_usage physical column order by recreating table
    op.execute('ALTER TABLE credit_usage RENAME TO credit_usage_old;')
    
    op.execute('''
        CREATE TABLE credit_usage (
            id UUID PRIMARY KEY,
            organization_id VARCHAR NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
            operation_type VARCHAR NOT NULL,
            credits_used NUMERIC(18, 6) NOT NULL DEFAULT 0.0,
            status credit_usage_status NOT NULL DEFAULT 'completed',
            cost_breakdown JSONB,
            reference_id VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
        )
    ''')
    
    op.execute('''
        INSERT INTO credit_usage (id, organization_id, operation_type, credits_used, status, cost_breakdown, reference_id, created_at, updated_at)
        SELECT id, organization_id, operation_type, credits_used, status, cost_breakdown, reference_id, created_at, updated_at 
        FROM credit_usage_old
    ''')
    
    op.execute('DROP TABLE credit_usage_old;')
    
    op.execute('CREATE INDEX ix_credit_usage_id ON credit_usage (id);')
    op.execute('CREATE INDEX ix_credit_usage_organization_id ON credit_usage (organization_id);')
    op.execute('CREATE INDEX ix_credit_usage_operation_type ON credit_usage (operation_type);')
    op.execute('CREATE INDEX ix_credit_usage_reference_id ON credit_usage (reference_id);')
    op.execute('CREATE INDEX ix_credit_usage_status ON credit_usage (status);')


def downgrade() -> None:
    """Downgrade schema."""
    pass
