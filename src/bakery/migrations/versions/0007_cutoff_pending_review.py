"""修改截止點 setting and 待確認 (pending reviews of held changes)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cutoff_days', sa.Integer(), nullable=False),
    sa.CheckConstraint('cutoff_days >= 0', name=op.f('ck_settings_cutoff_days_not_negative')),
    sa.CheckConstraint('id = 1', name=op.f('ck_settings_single_row')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_settings'))
    )
    op.create_table('pending_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('change_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reported_upload_id', sa.Integer(), nullable=True),
    sa.CheckConstraint(
        "status IN ('pending', 'confirmed', 'rejected', 'superseded')",
        name=op.f('ck_pending_reviews_review_status'),
    ),
    sa.ForeignKeyConstraint(['change_id'], ['changes.id'], name=op.f('fk_pending_reviews_change_id_changes')),
    sa.ForeignKeyConstraint(['decided_by_id'], ['accounts.id'], name=op.f('fk_pending_reviews_decided_by_id_accounts')),
    sa.ForeignKeyConstraint(['reported_upload_id'], ['uploads.id'], name=op.f('fk_pending_reviews_reported_upload_id_uploads')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pending_reviews')),
    sa.UniqueConstraint('change_id', name=op.f('uq_pending_reviews_change_id'))
    )
    op.create_index(op.f('ix_pending_reviews_status'), 'pending_reviews', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pending_reviews_status'), table_name='pending_reviews')
    op.drop_table('pending_reviews')
    op.drop_table('settings')
