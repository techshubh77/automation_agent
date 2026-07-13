"""refactor token schema to credit ledger

Revision ID: 02d2648de241
Revises: bca99665f6a0
Create Date: 2026-07-10 18:29:56.150793

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '02d2648de241'
down_revision: Union[str, Sequence[str], None] = 'bca99665f6a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename table
    op.rename_table('token_usage', 'credit_usage')
    
    # 2. Add new columns
    op.add_column('credit_usage', sa.Column('status', sa.String(), nullable=True))
    op.add_column('credit_usage', sa.Column('cost_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('credit_usage', sa.Column('reference_id', sa.String(), nullable=True))
    
    # 3. Migrate data
    op.execute(
        """
        UPDATE credit_usage 
        SET 
            status = 'completed',
            reference_id = conversation_id::text,
            cost_breakdown = json_build_object(
                'input_tokens', input_tokens,
                'output_tokens', output_tokens,
                'total_tokens', total_tokens
            )::jsonb
        """
    )
    
    # 4. Alter columns and rename
    op.alter_column('credit_usage', 'status', nullable=False)
    op.alter_column('credit_usage', 'total_tokens', new_column_name='credits_used')
    
    # 5. Drop old columns
    op.drop_constraint('token_usage_conversation_id_fkey', 'credit_usage', type_='foreignkey')
    op.drop_column('credit_usage', 'input_tokens')
    op.drop_column('credit_usage', 'output_tokens')
    op.drop_column('credit_usage', 'conversation_id')
    
    # 6. Update organizations
    op.add_column('organizations', sa.Column('credit_balance', sa.BigInteger(), nullable=True))
    op.execute("UPDATE organizations SET credit_balance = 0")
    op.alter_column('organizations', 'credit_balance', nullable=False)
    op.drop_column('organizations', 'token_used')
    op.drop_column('organizations', 'token_limit')

    # 7. Update Indexes
    op.execute("ALTER INDEX IF EXISTS ix_token_usage_id RENAME TO ix_credit_usage_id")
    op.execute("ALTER INDEX IF EXISTS ix_token_usage_operation_type RENAME TO ix_credit_usage_operation_type")
    op.execute("ALTER INDEX IF EXISTS ix_token_usage_organization_id RENAME TO ix_credit_usage_organization_id")
    
    op.create_index(op.f('ix_credit_usage_reference_id'), 'credit_usage', ['reference_id'], unique=False)
    op.create_index(op.f('ix_credit_usage_status'), 'credit_usage', ['status'], unique=False)


def downgrade() -> None:
    # 1. Reverse indexes
    op.drop_index(op.f('ix_credit_usage_status'), table_name='credit_usage')
    op.drop_index(op.f('ix_credit_usage_reference_id'), table_name='credit_usage')
    op.drop_index(op.f('ix_credit_usage_organization_id'), table_name='credit_usage')
    op.drop_index(op.f('ix_credit_usage_operation_type'), table_name='credit_usage')
    op.drop_index(op.f('ix_credit_usage_id'), table_name='credit_usage')
    
    op.create_index('ix_token_usage_organization_id', 'credit_usage', ['organization_id'], unique=False)
    op.create_index('ix_token_usage_operation_type', 'credit_usage', ['operation_type'], unique=False)
    op.create_index('ix_token_usage_id', 'credit_usage', ['id'], unique=False)
    op.create_index('ix_token_usage_conversation_id', 'credit_usage', ['conversation_id'], unique=False)

    # 2. Reverse organizations
    op.add_column('organizations', sa.Column('token_limit', sa.BIGINT(), autoincrement=False, nullable=True))
    op.add_column('organizations', sa.Column('token_used', sa.BIGINT(), autoincrement=False, nullable=True))
    op.execute("UPDATE organizations SET token_used = 0")
    op.alter_column('organizations', 'token_used', nullable=False)
    op.drop_column('organizations', 'credit_balance')

    # 3. Add old columns back to credit_usage
    op.add_column('credit_usage', sa.Column('conversation_id', sa.UUID(), autoincrement=False, nullable=True))
    op.add_column('credit_usage', sa.Column('output_tokens', sa.BIGINT(), autoincrement=False, nullable=True))
    op.add_column('credit_usage', sa.Column('input_tokens', sa.BIGINT(), autoincrement=False, nullable=True))
    
    # 4. Migrate data back
    op.execute(
        """
        UPDATE credit_usage 
        SET 
            conversation_id = CASE WHEN reference_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN reference_id::uuid ELSE NULL END,
            input_tokens = (cost_breakdown->>'input_tokens')::bigint,
            output_tokens = (cost_breakdown->>'output_tokens')::bigint
        """
    )
    
    op.alter_column('credit_usage', 'input_tokens', nullable=False)
    op.alter_column('credit_usage', 'output_tokens', nullable=False)
    
    op.alter_column('credit_usage', 'credits_used', new_column_name='total_tokens')
    
    op.create_foreign_key('token_usage_conversation_id_fkey', 'credit_usage', 'conversations', ['conversation_id'], ['id'], ondelete='SET NULL')
    
    # 5. Drop new columns
    op.drop_column('credit_usage', 'reference_id')
    op.drop_column('credit_usage', 'cost_breakdown')
    op.drop_column('credit_usage', 'status')
    
    # 6. Rename table back
    op.rename_table('credit_usage', 'token_usage')
