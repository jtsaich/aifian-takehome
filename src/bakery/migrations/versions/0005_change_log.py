"""change log: changes (one per order per upload that brought it in new or changed) and their field entries, append-only

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# 修改紀錄 is only ever added to: no UPDATE, no DELETE, on either table.
CHANGE_LOG_APPEND_ONLY_FUNCTION = """
CREATE FUNCTION change_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'the change log is append-only: % on % is not allowed', TG_OP, TG_TABLE_NAME;
END
$$
"""

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('changes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('upload_id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('is_new_order', sa.Boolean(), nullable=False),
    sa.Column('kinds', sa.ARRAY(sa.String(length=32)), nullable=False),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.CheckConstraint("decision IN ('applied', 'held')", name=op.f('ck_changes_change_decision')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_changes_order_id_orders')),
    sa.ForeignKeyConstraint(['upload_id'], ['uploads.id'], name=op.f('fk_changes_upload_id_uploads')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_changes'))
    )
    op.create_index(op.f('ix_changes_order_id'), 'changes', ['order_id'], unique=False)
    op.create_index(op.f('ix_changes_upload_id'), 'changes', ['upload_id'], unique=False)
    op.create_table('change_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('change_id', sa.Integer(), nullable=False),
    sa.Column('field', sa.String(length=16), nullable=False),
    sa.Column('product_code', sa.String(length=16), nullable=True),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.CheckConstraint(
        "field IN ('orderer_name', 'phone', 'received_on', 'pickup_on', 'banquet_on', "
        "'couple_names', 'taken_by', 'quantity', 'note', 'status')",
        name=op.f('ck_change_entries_change_field'),
    ),
    sa.ForeignKeyConstraint(['change_id'], ['changes.id'], name=op.f('fk_change_entries_change_id_changes')),
    sa.ForeignKeyConstraint(['product_code'], ['products.code'], name=op.f('fk_change_entries_product_code_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_change_entries'))
    )
    op.create_index(op.f('ix_change_entries_change_id'), 'change_entries', ['change_id'], unique=False)
    op.execute(CHANGE_LOG_APPEND_ONLY_FUNCTION)
    for table in ('changes', 'change_entries'):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION change_log_append_only()"
        )


def downgrade() -> None:
    for table in ('change_entries', 'changes'):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION change_log_append_only()")
    op.drop_index(op.f('ix_change_entries_change_id'), table_name='change_entries')
    op.drop_table('change_entries')
    op.drop_index(op.f('ix_changes_upload_id'), table_name='changes')
    op.drop_index(op.f('ix_changes_order_id'), table_name='changes')
    op.drop_table('changes')
