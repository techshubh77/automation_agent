"""add_document_status_index

Revision ID: 288e66e87c10
Revises: 28855ce9fb7e
Create Date: 2026-07-13 13:02:50.500267

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '288e66e87c10'
down_revision: Union[str, Sequence[str], None] = '28855ce9fb7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add index on documents.status for fast "active job" lookups.
    # Without this, every upload check does a full-table scan across all documents.
    op.create_index("ix_documents_status", "documents", ["status"], unique=False)

    # 2. Add composite index for the most common query pattern:
    # "find active jobs for a specific organization"
    op.create_index(
        "ix_documents_org_status",
        "documents",
        ["organization_id", "status"],
        unique=False,
    )

    # 3. Auto-recover any CURRENTLY stale orphaned documents.
    # Documents stuck in pending/processing for > 30 minutes are considered dead.
    # This one-time migration fixes any pre-existing orphans in production.
    op.execute(
        """
        UPDATE documents
        SET 
            status = 'failed',
            error_message = 'Auto-recovered by migration: document was stuck in ' || status ||
                            ' state for over 30 minutes. Please re-upload the file.'
        WHERE status IN ('pending', 'processing')
          AND updated_at < NOW() - INTERVAL '30 minutes'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_documents_org_status", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
