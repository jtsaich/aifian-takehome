"""客人資料: each 客人's 喜餅訂單 history, derived from the orders on every read.

A 客人 is one normalized phone (`bakery.phone.normalize_phone`). Nothing is stored
per customer, so whatever changes an order's phone (a 修改, an 歷史資料 import)
changes the customer view with it. Pages refer to a 客人 by one of their orders'
ids, never by the phone, so phones stay out of URLs and request logs.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from bakery.models import LineStatus, Order, Store
from bakery.phone import normalize_phone
from bakery.xlsx import download_bytes, finish_sheet


@dataclass(frozen=True)
class CustomerOrder:
    order: Order
    boxes: int  # 盒數 of the lines that are not cancelled

    @property
    def cancelled(self) -> bool:
        """Every line cancelled."""
        return all(line.status == LineStatus.CANCELLED for line in self.order.lines)


@dataclass(frozen=True)
class Customer:
    phone: str  # normalized
    orders: tuple[CustomerOrder, ...]  # by 接單日, oldest first

    @property
    def key(self) -> int:
        """The id the pages use for this 客人: their first order's."""
        return self.orders[0].order.id

    @property
    def order_count(self) -> int:
        return len(self.orders)

    @property
    def total_boxes(self) -> int:
        return sum(o.boxes for o in self.orders)

    @property
    def first_received_on(self) -> date:
        return self.orders[0].order.received_on

    @property
    def latest_received_on(self) -> date:
        return self.orders[-1].order.received_on

    @property
    def stores(self) -> tuple[Store, ...]:
        """Every 門市 they ordered at, in the order they first did."""
        seen: dict[str, Store] = {}
        for o in self.orders:
            seen.setdefault(o.order.store_code, o.order.store)
        return tuple(seen.values())

    @property
    def orderer_names(self) -> tuple[str, ...]:
        """Each different 訂購人姓名, as first written; spacing and full-width differences are the same name."""
        seen: dict[str, str] = {}
        for o in self.orders:
            if name := o.order.orderer_name:
                seen.setdefault(_comparable_name(name), name)
        return tuple(seen.values())

    @property
    def has_several_names(self) -> bool:
        return len(self.orderer_names) > 1


@dataclass(frozen=True)
class CustomerRecords:
    customers: tuple[Customer, ...]  # most orders first, then most recent 接單日
    # Orders with no phone or one `normalize_phone` rejects: on no 客人's record.
    unmatched: tuple[Order, ...]


def customer_records(session: Session) -> CustomerRecords:
    by_phone: dict[str, list[CustomerOrder]] = {}
    unmatched: list[Order] = []
    for order in _all_orders(session):
        phone = normalize_phone(order.phone) if order.phone else None
        if phone is None:
            unmatched.append(order)
        else:
            by_phone.setdefault(phone, []).append(CustomerOrder(order, _boxes(order)))
    customers = [Customer(phone, tuple(orders)) for phone, orders in by_phone.items()]
    customers.sort(key=lambda c: (-c.order_count, -c.latest_received_on.toordinal(), c.phone))
    unmatched.sort(key=lambda o: (o.received_on, o.id), reverse=True)
    return CustomerRecords(tuple(customers), tuple(unmatched))


def customer_of_order(session: Session, order_id: int) -> Customer | None:
    """The 客人 who placed order `order_id`; None if there is no such order or its phone is unusable."""
    return next(
        (
            c
            for c in customer_records(session).customers
            if any(o.order.id == order_id for o in c.orders)
        ),
        None,
    )


def _all_orders(session: Session) -> list[Order]:
    return list(
        session.scalars(
            select(Order)
            .options(joinedload(Order.store), selectinload(Order.lines))
            .order_by(Order.received_on, Order.id)
        )
    )


CUSTOMER_COLUMNS = (
    "電話", "訂單數", "總盒數", "第一次接單日", "最近一次接單日", "下過單的門市", "訂購人姓名", "姓名不一致",
)
ORDER_COLUMNS = ("電話", "門市", "單號", "接單日", "取貨日", "訂購人姓名", "電話（原始寫法）", "盒數", "狀態")


def customer_records_xlsx(records: CustomerRecords, now: datetime) -> bytes:
    """The 客人資料 page as a workbook: one sheet of 客人, one of their 喜餅訂單."""
    wb = Workbook()
    people = wb.active
    people.title = "客人"
    people.append(CUSTOMER_COLUMNS)
    orders = wb.create_sheet("訂單")
    orders.append(ORDER_COLUMNS)
    for c in records.customers:
        people.append(
            (
                c.phone,
                c.order_count,
                c.total_boxes,
                c.first_received_on,
                c.latest_received_on,
                "、".join(s.name for s in c.stores),
                "、".join(c.orderer_names),
                "是" if c.has_several_names else "",
            )
        )
        for co in c.orders:
            o = co.order
            orders.append(
                (
                    c.phone,
                    o.store.name,
                    o.order_no,
                    o.received_on,
                    o.pickup_on,
                    o.orderer_name,
                    o.phone,
                    co.boxes,
                    "全部取消" if co.cancelled else "",
                )
            )
    for ws in (people, orders):
        finish_sheet(ws, date_columns="DE")  # the two date columns of both sheets
    return download_bytes(wb, now)


def _boxes(order: Order) -> int:
    return sum(line.quantity for line in order.lines if line.status != LineStatus.CANCELLED)


def _comparable_name(name: str) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", name))
