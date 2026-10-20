"""總表: every 門市's 訂單明細 in one list, optionally narrowed to a 門市 and/or 取貨日."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, joinedload

from bakery.models import Order, OrderLine


def master_list(
    session: Session, *, store_code: str | None = None, pickup_on: date | None = None
) -> list[OrderLine]:
    """Lines (with their order, store and product loaded), by 取貨日, 門市, 單號."""
    stmt = (
        select(OrderLine)
        .join(OrderLine.order)
        .options(
            contains_eager(OrderLine.order).joinedload(Order.store),
            joinedload(OrderLine.product),
        )
        .order_by(Order.pickup_on, Order.store_code, Order.order_no, OrderLine.id)
    )
    if store_code:
        stmt = stmt.where(Order.store_code == store_code)
    if pickup_on:
        stmt = stmt.where(Order.pickup_on == pickup_on)
    return list(session.scalars(stmt))
