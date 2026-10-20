"""In-memory mock 喜餅訂單 and writing them into template-format sheets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from bakery import template as t

# How date cells are written: a real Excel date, or text the way staff type it.
DATE_EXCEL = "excel"
DATE_ROC = "roc"  # 民國年, e.g. 115/11/08


def roc_text(d: date) -> str:
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def slash_text(d: date) -> str:
    """How dates appear in reply text and in the 對照表."""
    return f"{d.year}/{d.month:02d}/{d.day:02d}"


@dataclass
class MockLine:
    product: str  # exactly as typed into the cell (canonical, alias or unknown)
    quantity: Any  # normally int; seeded errors may use other values
    note: str = ""
    status: str = ""
    # Per-row overrides of any column (used to seed inconsistent order fields).
    cells: dict[str, Any] = field(default_factory=dict)
    row: int = 0  # Excel row, filled in when written


@dataclass
class MockOrder:
    order_no: str | None
    orderer_name: str
    phone: str  # as typed
    received_on: date
    pickup_on: date
    banquet_on: date | None
    couple_names: str
    taken_by: str
    lines: list[MockLine]
    date_style: str = DATE_EXCEL
    # Order-level overrides (e.g. an unparseable 取貨日) and store-added columns.
    cells: dict[str, Any] = field(default_factory=dict)
    sheet: str = ""  # filled in when written

    @property
    def rows(self) -> list[int]:
        return [line.row for line in self.lines]


def _date_cell(value: date | None, style: str) -> Any:
    if value is None:
        return None
    return roc_text(value) if style == DATE_ROC else value


def _cell_value(order: MockOrder, line: MockLine, column: str) -> Any:
    if column in line.cells:
        return line.cells[column]
    if column in order.cells:
        return order.cells[column]
    match column:
        case t.COL_ORDER_NO:
            return order.order_no
        case t.COL_ORDERER_NAME:
            return order.orderer_name
        case t.COL_PHONE:
            return order.phone
        case t.COL_RECEIVED_ON:
            return _date_cell(order.received_on, order.date_style)
        case t.COL_PICKUP_ON:
            return _date_cell(order.pickup_on, order.date_style)
        case t.COL_BANQUET_ON:
            return _date_cell(order.banquet_on, order.date_style)
        case t.COL_COUPLE_NAMES:
            return order.couple_names
        case t.COL_TAKEN_BY:
            return order.taken_by
        case t.COL_PRODUCT:
            return line.product
        case t.COL_QUANTITY:
            return line.quantity
        case t.COL_NOTE:
            return line.note or None
        case t.COL_STATUS:
            return line.status or None
    return None


def write_orders(
    ws: Worksheet,
    orders: Sequence[MockOrder],
    columns: Sequence[str],
    first_row: int = t.FIRST_DATA_ROW,
) -> None:
    """Write one row per 訂單明細 and record each line's Excel row.

    `columns` gives the field written under each header position. It differs
    from the sheet's header text only where a store uses a synonym (the header
    says 手機, the field is 電話).
    """
    row = first_row
    for order in orders:
        order.sheet = ws.title
        for line in order.lines:
            line.row = row
            for col_idx, column in enumerate(columns, start=1):
                value = _cell_value(order, line, column)
                if value is None:
                    continue
                cell = ws.cell(row=row, column=col_idx, value=value)
                if isinstance(value, date):
                    cell.number_format = t.DATE_NUMBER_FORMAT
                elif column in t.TEXT_COLUMNS:
                    cell.number_format = "@"
            row += 1
