"""Merge one 上傳's parsed 喜餅訂單 into the stored orders, logging every 新單 and 修改.

ADR 0001: an upload is a batch. Orders and 訂單明細 absent from the file are left
untouched. A 單號 on record whose content is identical is left alone and not
logged; one with different content is a 修改, classified and applied or held as
bakery.changes.decide says.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bakery.changes import apply_diffs, decide, detect_change, new_order_diffs
from bakery.models import Change, ChangeDecision, ChangeEntry, ChangeKind, Order, Upload
from bakery.outcome import FieldDiff, OrderChange
from bakery.parsing import ParsedOrder


@dataclass(frozen=True)
class MergeResult:
    new_order_nos: tuple[str, ...]
    unchanged_order_nos: tuple[str, ...]
    changes: tuple[OrderChange, ...]


def merge_orders(
    session: Session,
    *,
    upload: Upload,
    store_code: str,
    orders: Sequence[ParsedOrder],
    historical: bool = False,
) -> MergeResult:
    """`historical`: a 歷史資料匯入. New orders are flagged is_historical and no change
    is held (bakery.changes.decide); the caller keeps orders received after go-live out."""
    existing = {
        o.order_no: o
        for o in session.scalars(
            select(Order)
            .where(Order.store_code == store_code, Order.order_no.in_([p.order_no for p in orders]))
            .options(selectinload(Order.lines))
        )
    }
    new: list[str] = []
    unchanged: list[str] = []
    changes: list[OrderChange] = []
    for parsed in orders:
        order = existing.get(parsed.order_no)
        if order is None:
            order = Order(store_code=store_code, order_no=parsed.order_no, is_historical=historical)
            session.add(order)
            diffs = new_order_diffs(parsed)
            apply_diffs(order, diffs)
            _log(session, upload, order, (), diffs, ChangeDecision.APPLIED, is_new_order=True)
            new.append(parsed.order_no)
            continue

        detected = detect_change(order, parsed)
        if detected is None:
            unchanged.append(parsed.order_no)
            continue
        decision = decide(detected, historical=historical)
        _log(session, upload, order, detected.kinds, detected.diffs, decision, is_new_order=False)
        if decision == ChangeDecision.APPLIED:
            apply_diffs(order, detected.diffs)
        changes.append(OrderChange(parsed.order_no, detected.kinds, detected.diffs, decision))
    session.flush()
    return MergeResult(tuple(new), tuple(unchanged), tuple(changes))


def _log(
    session: Session,
    upload: Upload,
    order: Order,
    kinds: Sequence[ChangeKind],
    diffs: Sequence[FieldDiff],
    decision: ChangeDecision,
    *,
    is_new_order: bool,
) -> None:
    session.add(
        Change(
            upload=upload,
            order=order,
            is_new_order=is_new_order,
            kinds=[k.value for k in kinds],
            decision=decision,
            entries=[
                ChangeEntry(
                    field=d.field, product_code=d.product_code, old_value=d.old, new_value=d.new
                )
                for d in diffs
            ],
        )
    )
