"""Warnings on accepted 喜餅訂單: kept as they are, but pointed out to the 傳檔者.

Pure: parsed orders, today (Taipei) and the store's other stored orders in;
findings out.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from bakery.outcome import Finding, FindingKind, Severity
from bakery.parsing import ParsedOrder, group_rows
from bakery.phone import normalize_phone, phone_problem

# A 取貨日 this many days from today or fewer (today included) is too soon for the kitchen.
PICKUP_TOO_SOON_DAYS = 3
# A 訂單明細 with more 盒 than this is probably a typo.
QUANTITY_WARNING_OVER = 300


@dataclass(frozen=True)
class StoredOrder:
    """Another 喜餅訂單 already on record for the same 門市."""

    order_no: str
    phone: str | None
    pickup_on: date


def order_warnings(
    orders: Sequence[ParsedOrder], today: date, stored: Iterable[StoredOrder] = ()
) -> list[Finding]:
    """Warnings for `orders`. Orders whose lines are all cancelled are not checked."""
    live = [o for o in orders if any(not line.cancelled for line in o.lines)]
    findings: list[Finding] = []
    for order in live:
        findings.extend(_order_warnings(order, today))
    findings.extend(_duplicate_phone_pickup(live, stored))
    return findings


def _order_warnings(order: ParsedOrder, today: date) -> Iterable[Finding]:
    def warning(kind: FindingKind, locations=None, **detail) -> Finding:
        return Finding(kind, Severity.WARNING, locations or order.locations, (order.order_no,), detail)

    days = (order.pickup_on - today).days
    if days < 0:
        yield warning(FindingKind.PICKUP_IN_PAST, pickup_on=order.pickup_on)
    elif days <= PICKUP_TOO_SOON_DAYS:
        yield warning(FindingKind.PICKUP_TOO_SOON, pickup_on=order.pickup_on, days=days)

    if order.phone and (problem := phone_problem(order.phone)):
        yield warning(FindingKind.PHONE_FORMAT, phone=order.phone, problem=problem)

    for line in order.lines:
        if not line.cancelled and line.quantity > QUANTITY_WARNING_OVER:
            yield warning(
                FindingKind.QUANTITY_OVER_THRESHOLD,
                group_rows([(line.sheet, line.row)]),
                product=line.product_name,
                quantity=line.quantity,
            )


def _duplicate_phone_pickup(
    orders: Sequence[ParsedOrder], stored: Iterable[StoredOrder]
) -> Iterable[Finding]:
    """One warning per (phone, 取貨日) shared by several 單號, in this file or on record."""
    in_file = {o.order_no for o in orders}
    groups: dict[tuple[str, date], tuple[list[ParsedOrder], list[str]]] = {}
    for o in orders:
        if o.phone and (phone := normalize_phone(o.phone)):
            groups.setdefault((phone, o.pickup_on), ([], []))[0].append(o)
    for s in stored:
        if s.order_no in in_file or not s.phone or not (phone := normalize_phone(s.phone)):
            continue
        group = groups.get((phone, s.pickup_on))
        if group is not None and s.order_no not in group[1]:
            group[1].append(s.order_no)

    for file_orders, stored_nos in groups.values():
        if len(file_orders) + len(stored_nos) < 2:
            continue
        yield Finding(
            FindingKind.DUPLICATE_PHONE_PICKUP,
            Severity.WARNING,
            group_rows((loc.sheet, r) for o in file_orders for loc in o.locations for r in loc.rows),
            tuple(o.order_no for o in file_orders),
            {"stored_order_nos": tuple(stored_nos)},
        )
