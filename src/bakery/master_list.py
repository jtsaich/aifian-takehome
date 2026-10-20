"""總表: every 門市's 訂單明細 in one list, optionally narrowed to a 門市 and/or 取貨日."""

from __future__ import annotations

from datetime import date, datetime

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, joinedload

from bakery.models import LineStatus, Order, OrderLine
from bakery.xlsx import workbook_bytes

# The page's columns and the .xlsx's, in order.
COLUMNS = (
    "取貨日", "門市", "單號", "品項", "盒數", "狀態", "備註",
    "訂購人姓名", "電話", "接單日", "宴客日", "新人姓名", "接單人",
)
_DATE_COLUMNS = "AJK"  # 取貨日, 接單日, 宴客日
_DATE_FORMAT = "yyyy/mm/dd"


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


def status_text(line: OrderLine) -> str:
    """The 狀態 column: 取消 and/or 歷史資料."""
    parts = []
    if line.status == LineStatus.CANCELLED:
        parts.append("取消")
    if line.order.is_historical:
        parts.append("歷史資料")
    return "、".join(parts)


def master_list_xlsx(lines: list[OrderLine], now: datetime) -> bytes:
    """The 總表 page's rows as a workbook."""
    wb = Workbook()
    ws = wb.active
    ws.title = "總表"
    ws.append(COLUMNS)
    for line in lines:
        o = line.order
        ws.append(
            (
                o.pickup_on, o.store.name, o.order_no, line.product.name, line.quantity,
                status_text(line), line.note, o.orderer_name, o.phone, o.received_on,
                o.banquet_on, o.couple_names, o.taken_by,
            )
        )
    for col in _DATE_COLUMNS:
        for cell in ws[col][1:]:
            cell.number_format = _DATE_FORMAT
    ws.freeze_panes = "A2"
    return workbook_bytes(wb, now.replace(tzinfo=None))
