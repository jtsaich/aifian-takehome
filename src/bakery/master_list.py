"""總表: every 門市's 訂單明細 in one list, optionally narrowed to a 門市 and/or 取貨日."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from openpyxl import Workbook
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from bakery.models import (
    BindingStatus,
    Change,
    ChangeDecision,
    LineStatus,
    Order,
    OrderLine,
    PendingReview,
    ReviewStatus,
    StoreBinding,
    Upload,
)
from bakery.xlsx import download_bytes, finish_sheet

# The page's columns and the .xlsx's, in order.
COLUMNS = (
    "取貨日", "門市", "單號", "品項", "盒數", "狀態", "備註",
    "訂購人姓名", "電話", "接單日", "宴客日", "新人姓名", "接單人",
)
_DATE_COLUMNS = "AJK"  # 取貨日, 接單日, 宴客日
UPLOADER_PENDING = "傳檔者待確認"


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


def line_statuses(session: Session, lines: Sequence[OrderLine]) -> dict[int, str]:
    """The 狀態 column by line id: 取消, 歷史資料, and 傳檔者待確認 (R8) when the order's
    latest content that counts came from a 傳檔者 whose 門市綁定 總部 hasn't confirmed yet."""
    pending = _orders_from_pending_uploaders(session, {line.order_id for line in lines})
    statuses = {}
    for line in lines:
        parts = []
        if line.status == LineStatus.CANCELLED:
            parts.append("取消")
        if line.order.is_historical:
            parts.append("歷史資料")
        if line.order_id in pending:
            parts.append(UPLOADER_PENDING)
        statuses[line.id] = "、".join(parts)
    return statuses


def _orders_from_pending_uploaders(session: Session, order_ids: set[int]) -> set[int]:
    if not order_ids:
        return set()
    # Content that counts: applied at once, or held and then confirmed by 總部.
    counted = (
        select(Change.order_id, func.max(Change.id).label("change_id"))
        .outerjoin(PendingReview, PendingReview.change_id == Change.id)
        .where(
            Change.order_id.in_(order_ids),
            or_(Change.decision == ChangeDecision.APPLIED, PendingReview.status == ReviewStatus.CONFIRMED),
        )
        .group_by(Change.order_id)
        .subquery()
    )
    return set(
        session.scalars(
            select(counted.c.order_id)
            .join(Change, Change.id == counted.c.change_id)
            .join(Upload, Upload.id == Change.upload_id)
            .join(StoreBinding, StoreBinding.uploader_id == Upload.uploader_id)
            .where(StoreBinding.status == BindingStatus.PENDING)
        )
    )


def master_list_xlsx(lines: list[OrderLine], statuses: dict[int, str], now: datetime) -> bytes:
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
                statuses[line.id] or None, line.note, o.orderer_name, o.phone, o.received_on,
                o.banquet_on, o.couple_names, o.taken_by,
            )
        )
    finish_sheet(ws, date_columns=_DATE_COLUMNS)
    return download_bytes(wb, now)
