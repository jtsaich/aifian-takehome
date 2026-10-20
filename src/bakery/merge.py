"""Merge one 上傳's parsed 喜餅訂單 into the stored orders.

ADR 0001: an upload is a batch. Orders and 訂單明細 absent from the file are left
untouched; a 單號 already on record is overwritten with the file's content
(no change detection or change log yet).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bakery.models import LineStatus, Order, OrderLine
from bakery.parsing import ParsedOrder


def merge_orders(session: Session, *, store_code: str, orders: Sequence[ParsedOrder]) -> None:
    existing = {
        o.order_no: o
        for o in session.scalars(
            select(Order)
            .where(Order.store_code == store_code, Order.order_no.in_([p.order_no for p in orders]))
            .options(selectinload(Order.lines))
        )
    }
    for parsed in orders:
        order = existing.get(parsed.order_no)
        if order is None:
            order = Order(store_code=store_code, order_no=parsed.order_no)
            session.add(order)
        order.orderer_name = parsed.orderer_name
        order.phone = parsed.phone
        order.received_on = parsed.received_on
        order.pickup_on = parsed.pickup_on
        order.banquet_on = parsed.banquet_on
        order.couple_names = parsed.couple_names
        order.taken_by = parsed.taken_by

        lines = {line.product_code: line for line in order.lines}
        for p in parsed.lines:
            line = lines.get(p.product_code)
            if line is None:
                line = lines[p.product_code] = OrderLine(product_code=p.product_code)
                order.lines.append(line)
            line.quantity = p.quantity
            line.note = p.note
            line.status = LineStatus.CANCELLED if p.cancelled else LineStatus.ACTIVE
    session.flush()
