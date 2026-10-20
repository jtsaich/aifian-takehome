"""LINE webhook and 門市綁定: store_bindings, line_webhook_events, uploads without a known
uploader, and the reason a processing failure is kept for 總部

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('store_bindings',
    sa.Column('uploader_id', sa.Integer(), nullable=False),
    sa.Column('store_code', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('confirmed_by_id', sa.Integer(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'confirmed')", name=op.f('ck_store_bindings_binding_status')),
    sa.ForeignKeyConstraint(['confirmed_by_id'], ['accounts.id'], name=op.f('fk_store_bindings_confirmed_by_id_accounts')),
    sa.ForeignKeyConstraint(['store_code'], ['stores.code'], name=op.f('fk_store_bindings_store_code_stores')),
    sa.ForeignKeyConstraint(['uploader_id'], ['uploaders.id'], name=op.f('fk_store_bindings_uploader_id_uploaders')),
    sa.PrimaryKeyConstraint('uploader_id', name=op.f('pk_store_bindings'))
    )
    op.create_table('line_webhook_events',
    sa.Column('webhook_event_id', sa.String(length=64), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('upload_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['upload_id'], ['uploads.id'], name=op.f('fk_line_webhook_events_upload_id_uploads')),
    sa.PrimaryKeyConstraint('webhook_event_id', name=op.f('pk_line_webhook_events'))
    )
    # LINE does not always say who sent a file in a group.
    op.alter_column('uploads', 'uploader_id', existing_type=sa.Integer(), nullable=True)
    # A processing result like reply_text, so the append-only trigger leaves it writable.
    op.add_column('uploads', sa.Column('failure_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('uploads', 'failure_reason')
    op.alter_column('uploads', 'uploader_id', existing_type=sa.Integer(), nullable=False)
    op.drop_table('line_webhook_events')
    op.drop_table('store_bindings')
