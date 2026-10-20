"""Who added a 品項 / 品項別名 and set the 修改截止點; LINE events whose file could not be downloaded

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('products', sa.Column('created_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_products_created_by_id_accounts'), 'products', 'accounts', ['created_by_id'], ['id']
    )
    op.add_column('product_aliases', sa.Column('created_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_product_aliases_created_by_id_accounts'), 'product_aliases', 'accounts', ['created_by_id'], ['id']
    )
    op.add_column('settings', sa.Column('cutoff_days_set_by_id', sa.Integer(), nullable=True))
    op.add_column('settings', sa.Column('cutoff_days_set_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f('fk_settings_cutoff_days_set_by_id_accounts'), 'settings', 'accounts', ['cutoff_days_set_by_id'], ['id']
    )
    op.add_column(
        'line_webhook_events',
        sa.Column('download_failed', sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('line_webhook_events', 'download_failed')
    op.drop_constraint(op.f('fk_settings_cutoff_days_set_by_id_accounts'), 'settings', type_='foreignkey')
    op.drop_column('settings', 'cutoff_days_set_at')
    op.drop_column('settings', 'cutoff_days_set_by_id')
    op.drop_constraint(op.f('fk_product_aliases_created_by_id_accounts'), 'product_aliases', type_='foreignkey')
    op.drop_column('product_aliases', 'created_by_id')
    op.drop_constraint(op.f('fk_products_created_by_id_accounts'), 'products', type_='foreignkey')
    op.drop_column('products', 'created_by_id')
