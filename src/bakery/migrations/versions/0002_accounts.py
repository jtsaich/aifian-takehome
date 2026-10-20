"""accounts (hq / kitchen / owner logins) and the account that submitted an upload

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Same rule as 0001, with the submitting account now part of the immutable original.
UPLOADS_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION uploads_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'uploads are append-only: upload % cannot be deleted', OLD.id;
    END IF;
    IF (NEW.id, NEW.uploader_id, NEW.submitted_by_id, NEW.filename, NEW.content, NEW.size_bytes,
        NEW.sha256, NEW.received_at)
       IS DISTINCT FROM
       (OLD.id, OLD.uploader_id, OLD.submitted_by_id, OLD.filename, OLD.content, OLD.size_bytes,
        OLD.sha256, OLD.received_at)
    THEN
        RAISE EXCEPTION 'uploads are append-only: the original of upload % cannot be changed', OLD.id;
    END IF;
    RETURN NEW;
END
$$
"""

UPLOADS_APPEND_ONLY_FUNCTION_0001 = """
CREATE OR REPLACE FUNCTION uploads_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'uploads are append-only: upload % cannot be deleted', OLD.id;
    END IF;
    IF (NEW.id, NEW.uploader_id, NEW.filename, NEW.content, NEW.size_bytes, NEW.sha256, NEW.received_at)
       IS DISTINCT FROM
       (OLD.id, OLD.uploader_id, OLD.filename, OLD.content, OLD.size_bytes, OLD.sha256, OLD.received_at)
    THEN
        RAISE EXCEPTION 'uploads are append-only: the original of upload % cannot be changed', OLD.id;
    END IF;
    RETURN NEW;
END
$$
"""


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('hq', 'kitchen', 'owner')", name=op.f('ck_accounts_role')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_accounts')),
    sa.UniqueConstraint('username', name=op.f('uq_accounts_username'))
    )
    op.add_column('uploads', sa.Column('submitted_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_uploads_submitted_by_id_accounts'), 'uploads', 'accounts', ['submitted_by_id'], ['id'])
    op.execute(UPLOADS_APPEND_ONLY_FUNCTION)


def downgrade() -> None:
    op.execute(UPLOADS_APPEND_ONLY_FUNCTION_0001)
    op.drop_constraint(op.f('fk_uploads_submitted_by_id_accounts'), 'uploads', type_='foreignkey')
    op.drop_column('uploads', 'submitted_by_id')
    op.drop_table('accounts')
