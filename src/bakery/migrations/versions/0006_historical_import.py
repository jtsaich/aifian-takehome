"""歷史資料匯入: is_historical on orders and on the upload that imported them

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21 16:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Same rule as 0002, with is_historical now part of the immutable original.
UPLOADS_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION uploads_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'uploads are append-only: upload % cannot be deleted', OLD.id;
    END IF;
    IF (NEW.id, NEW.uploader_id, NEW.submitted_by_id, NEW.is_historical, NEW.filename, NEW.content,
        NEW.size_bytes, NEW.sha256, NEW.received_at)
       IS DISTINCT FROM
       (OLD.id, OLD.uploader_id, OLD.submitted_by_id, OLD.is_historical, OLD.filename, OLD.content,
        OLD.size_bytes, OLD.sha256, OLD.received_at)
    THEN
        RAISE EXCEPTION 'uploads are append-only: the original of upload % cannot be changed', OLD.id;
    END IF;
    RETURN NEW;
END
$$
"""

UPLOADS_APPEND_ONLY_FUNCTION_0002 = """
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

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('is_historical', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('uploads', sa.Column('is_historical', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute(UPLOADS_APPEND_ONLY_FUNCTION)


def downgrade() -> None:
    op.execute(UPLOADS_APPEND_ONLY_FUNCTION_0002)
    op.drop_column('uploads', 'is_historical')
    op.drop_column('orders', 'is_historical')
