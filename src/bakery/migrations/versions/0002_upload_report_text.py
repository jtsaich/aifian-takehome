"""upload report_text: the full reply when the LINE reply is cut at 5,000 characters

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A processing result like reply_text, so the append-only trigger leaves it writable.
    op.add_column('uploads', sa.Column('report_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('uploads', 'report_text')
