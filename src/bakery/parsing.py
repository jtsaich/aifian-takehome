"""Read a 範本 .xlsx into 喜餅訂單 / 訂單明細, grouped by 單號, with row-level errors.

Pure: bytes in, dataclasses out; no database. The 品項 list comes in as a
lookup so it follows what HQ maintains.

Tolerant of what stores actually send: headers in any order, header synonyms,
extra columns of their own, several order sheets, dates as Excel dates /
民國年 / 西元年 / month-day text. A bad row is dropped with an error finding and
the rest of the file is kept; an order whose rows disagree on order-level
fields (even across sheets) is dropped whole. Only a file that can't be read
as orders at all raises `FileRejected`.
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from openpyxl.worksheet.worksheet import Worksheet

from bakery import template as t
from bakery.outcome import (
    Failure,
    FailureKind,
    Finding,
    FindingKind,
    Severity,
    SheetRows,
    SkipReason,
)
from bakery.phone import phone_digits


@dataclass(frozen=True)
class ProductRef:
    code: str
    name: str  # canonical 品項 name


# 品項 name or 品項別名 -> the 品項. Exact match only (after trimming spaces).
ProductLookup = Mapping[str, ProductRef]

# Other ways stores label the template columns (compared after removing spaces).
HEADER_SYNONYMS: Mapping[str, str] = {
    synonym: column
    for column, synonyms in {
        t.COL_ORDER_NO: ("訂單編號", "訂單號碼", "訂單號", "單據號碼", "編號"),
        t.COL_ORDERER_NAME: ("訂購人", "姓名", "客人姓名", "客戶姓名", "訂購人名字"),
        t.COL_PHONE: ("手機", "手機號碼", "聯絡電話", "連絡電話", "電話號碼", "訂購人電話"),
        t.COL_RECEIVED_ON: ("接單日期", "訂購日", "訂購日期", "下單日", "下單日期"),
        t.COL_PICKUP_ON: ("取貨日期", "交貨日", "交貨日期", "取件日", "取餅日"),
        t.COL_BANQUET_ON: ("宴客日期", "結婚日", "訂婚日", "喜宴日", "婚宴日"),
        t.COL_COUPLE_NAMES: ("新人", "新郎新娘", "新人名字"),
        t.COL_TAKEN_BY: ("承辦人", "經手人", "接單人員", "接單員"),
        t.COL_PRODUCT: ("品名", "喜餅", "產品", "商品", "款式"),
        t.COL_QUANTITY: ("數量", "盒", "訂購盒數", "盒數量"),
        t.COL_NOTE: ("附註", "說明"),
        t.COL_STATUS: ("訂單狀態",),
    }.items()
    for synonym in synonyms
}
# A sheet is read as orders when its header row has at least these columns.
REQUIRED_COLUMNS: tuple[str, ...] = (
    t.COL_ORDER_NO,
    t.COL_RECEIVED_ON,
    t.COL_PICKUP_ON,
    t.COL_PRODUCT,
    t.COL_QUANTITY,
)
# The header row is searched for in the first rows of each sheet.
HEADER_SEARCH_ROWS = 10
STORE_CODE_LABEL = "門市代碼"
VERSION_LABEL = "範本版本"

# Order-level columns compared across the rows of one 單號 (單號 itself is the key).
_COMPARED_COLUMNS: tuple[str, ...] = tuple(c for c in t.ORDER_COLUMNS if c != t.COL_ORDER_NO)


@dataclass(frozen=True)
class ParsedLine:
    """訂單明細: one template row."""

    sheet: str
    row: int  # Excel row number, for pointing the 門市 at it
    product_code: str
    product_name: str
    quantity: int
    note: str | None
    cancelled: bool


@dataclass(frozen=True)
class ParsedOrder:
    """喜餅訂單: the order-level columns (identical on all its rows) and its rows."""

    order_no: str
    orderer_name: str | None
    phone: str | None
    received_on: date
    pickup_on: date
    banquet_on: date | None
    couple_names: str | None
    taken_by: str | None
    lines: tuple[ParsedLine, ...]

    @property
    def locations(self) -> tuple[SheetRows, ...]:
        return group_rows((line.sheet, line.row) for line in self.lines)


@dataclass(frozen=True)
class ParsedFile:
    store_code: str
    template_version: str | None
    orders: tuple[ParsedOrder, ...]  # accepted orders only
    findings: tuple[Finding, ...]  # row/order errors and skipped sheets
    rejected_rows: tuple[SheetRows, ...]
    sheet_names: tuple[str, ...]  # every sheet in workbook order, for ordering findings

    @property
    def line_count(self) -> int:
        return sum(len(o.lines) for o in self.orders)


class FileRejected(Exception):
    """The file as a whole can't be taken in; `failure` says why."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.kind.value)
        self.failure = failure


def is_template_file(file_bytes: bytes) -> bool:
    """Whether the file is a 範本: an .xlsx with the 門市代碼 and 範本版本 label cells
    near the top of some sheet. Other files sent to the LINE group are not ours to answer."""
    try:
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception:  # not an .xlsx at all: a photo, a PDF, a .docx...
        return False
    try:
        for ws in wb.worksheets:
            top = ws.iter_rows(min_row=1, max_row=HEADER_SEARCH_ROWS, values_only=True)
            labels = {_text(v) for row in top for v in row}
            if STORE_CODE_LABEL in labels and VERSION_LABEL in labels:
                return True
        return False
    finally:
        wb.close()


def parse_upload(file_bytes: bytes, products: ProductLookup, today: date) -> ParsedFile:
    """`today` (Taipei) resolves dates written without a year, e.g. 10/25."""
    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as exc:  # not an .xlsx, encrypted, corrupt: openpyxl raises many types
        raise FileRejected(Failure(FailureKind.UNREADABLE_FILE)) from exc

    sheets: list[_OrderSheet] = []
    findings: list[Finding] = []
    for ws in wb.worksheets:
        found = _order_sheet(ws)
        if found is not None:
            sheets.append(found)
        elif not _is_blank(ws):
            findings.append(_skipped(ws.title, SkipReason.NOT_TEMPLATE))
    if not sheets:
        raise FileRejected(Failure(FailureKind.NO_ORDER_SHEET))

    store_code = next((s.store_code for s in sheets if s.store_code), None)
    if store_code is None:
        raise FileRejected(Failure(FailureKind.MISSING_STORE_CODE))
    read: list[_OrderSheet] = []
    for s in sheets:
        if s.store_code not in (None, store_code):
            findings.append(_skipped(s.ws.title, SkipReason.OTHER_STORE, other_store_code=s.store_code))
        else:
            read.append(s)

    rejected: set[tuple[str, int]] = set()
    good_rows: dict[str, list[_Row]] = {}
    for s in read:
        for row in _rows(s, products, today):
            if isinstance(row, _Row):
                good_rows.setdefault(row.order_no, []).append(row)
            else:
                findings.extend(row)
                rejected.update((loc.sheet, r) for f in row for loc in f.locations for r in loc.rows)

    orders: list[ParsedOrder] = []
    for order_no, rows in good_rows.items():
        order_errors = _order_errors(order_no, rows)
        if order_errors:
            findings.extend(order_errors)
            rejected.update((r.sheet, r.row) for r in rows)
        else:
            orders.append(_order(order_no, rows))

    sheet_names = tuple(wb.sheetnames)
    position = {name: i for i, name in enumerate(sheet_names)}
    return ParsedFile(
        store_code=store_code,
        template_version=next((s.version for s in read if s.version), None),
        orders=tuple(orders),
        findings=sort_findings(findings, sheet_names),
        rejected_rows=group_rows(sorted(rejected, key=lambda sr: (position[sr[0]], sr[1]))),
        sheet_names=sheet_names,
    )


def sort_findings(findings: Iterable[Finding], sheet_names: Sequence[str]) -> tuple[Finding, ...]:
    """In file order: by the sheet and first row each finding points at."""
    position = {name: i for i, name in enumerate(sheet_names)}

    def key(f: Finding) -> tuple[int, int]:
        loc = f.locations[0]
        return (position.get(loc.sheet, len(position)), loc.rows[0] if loc.rows else 0)

    return tuple(sorted(findings, key=key))


def group_rows(refs: Iterable[tuple[str, int]]) -> tuple[SheetRows, ...]:
    """(sheet, row) pairs -> one SheetRows per sheet, in first-seen order."""
    by_sheet: dict[str, list[int]] = {}
    for sheet, row in refs:
        rows = by_sheet.setdefault(sheet, [])
        if row not in rows:
            rows.append(row)
    return tuple(SheetRows(sheet, tuple(rows)) for sheet, rows in by_sheet.items())


# ---------------------------------------------------------------- sheets


@dataclass(frozen=True)
class _OrderSheet:
    ws: Worksheet
    header_row: int
    columns: Mapping[str, int]  # template column -> 0-based index
    store_code: str | None
    version: str | None


def _order_sheet(ws: Worksheet) -> _OrderSheet | None:
    top = list(ws.iter_rows(min_row=1, max_row=HEADER_SEARCH_ROWS, values_only=True))
    for idx, values in enumerate(top):
        columns = _header_columns(values)
        if all(c in columns for c in REQUIRED_COLUMNS):
            above = top[:idx]
            return _OrderSheet(
                ws=ws,
                header_row=idx + 1,
                columns=columns,
                store_code=(code.upper() if (code := _label_value(above, STORE_CODE_LABEL)) else None),
                version=_label_value(above, VERSION_LABEL),
            )
    return None


def _header_columns(values: Sequence[Any]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for idx, value in enumerate(values):
        label = _text(value)
        if label is None:
            continue
        label = re.sub(r"\s", "", unicodedata.normalize("NFKC", label))
        column = label if label in t.COLUMNS else HEADER_SYNONYMS.get(label)
        if column is not None and column not in columns:
            columns[column] = idx
    return columns


def _label_value(rows_above_header: Sequence[Sequence[Any]], label: str) -> str | None:
    """The cell right of a label above the header (template: 門市代碼 A1→B1, 範本版本 E1→F1)."""
    for values in rows_above_header:
        for idx, value in enumerate(values):
            if _text(value) == label:
                return _text(values[idx + 1]) if idx + 1 < len(values) else None
    return None


def _is_blank(ws: Worksheet) -> bool:
    return all(_text(v) is None for row in ws.iter_rows(values_only=True) for v in row)


def _skipped(sheet: str, reason: SkipReason, **detail: Any) -> Finding:
    return Finding(
        FindingKind.SKIPPED_SHEET,
        Severity.INFO,
        (SheetRows(sheet),),
        detail={"reason": reason, **detail},
    )


# ---------------------------------------------------------------- rows


@dataclass(frozen=True)
class _Row:
    sheet: str
    row: int
    order_no: str
    fields: Mapping[str, Any]  # order-level columns, parsed
    product: ProductRef
    quantity: int
    note: str | None
    cancelled: bool


def _rows(
    s: _OrderSheet, products: ProductLookup, today: date
) -> Iterable[_Row | list[Finding]]:
    """Each non-blank data row: a parsed row, or the errors that drop it."""
    sheet = s.ws.title
    first = s.header_row + 1
    for row_no, values in enumerate(s.ws.iter_rows(min_row=first, values_only=True), start=first):
        cells = {c: values[i] if i < len(values) else None for c, i in s.columns.items()}
        if all(_text(v) is None for v in cells.values()):
            continue
        yield _row(sheet, row_no, cells, products, today)


def _row(
    sheet: str, row_no: int, cells: Mapping[str, Any], products: ProductLookup, today: date
) -> _Row | list[Finding]:
    order_no = _text(cells.get(t.COL_ORDER_NO))
    where = (SheetRows(sheet, (row_no,)),)
    order_nos = (order_no,) if order_no else ()
    errors: list[Finding] = []

    def error(kind: FindingKind, **detail: Any) -> None:
        errors.append(Finding(kind, Severity.ERROR, where, order_nos, detail))

    if order_no is None:
        error(FindingKind.MISSING_ORDER_NO)

    dates: dict[str, date | None] = {}
    for column in (t.COL_RECEIVED_ON, t.COL_PICKUP_ON, t.COL_BANQUET_ON):
        raw = cells.get(column)
        if _text(raw) is None:
            dates[column] = None
            if column != t.COL_BANQUET_ON:
                error(FindingKind.MISSING_DATE, column=column)
            continue
        parsed = parse_date(raw, today)
        if parsed is None:
            error(FindingKind.UNPARSEABLE_DATE, column=column, value=_display_text(raw))
        dates[column] = parsed

    raw_quantity = cells.get(t.COL_QUANTITY)
    quantity = parse_quantity(raw_quantity)
    if quantity is None:
        error(FindingKind.INVALID_QUANTITY, value=_display_text(raw_quantity))

    product_text = _text(cells.get(t.COL_PRODUCT))
    product = products.get(product_text) if product_text else None
    if product is None:
        error(FindingKind.UNKNOWN_PRODUCT, value=product_text)

    status = _text(cells.get(t.COL_STATUS))
    if status not in (None, t.STATUS_CANCELLED):
        error(FindingKind.INVALID_STATUS, value=status)

    if errors:
        return errors
    assert order_no is not None and product is not None and quantity is not None
    return _Row(
        sheet=sheet,
        row=row_no,
        order_no=order_no,
        fields={
            t.COL_ORDERER_NAME: _text(cells.get(t.COL_ORDERER_NAME)),
            t.COL_PHONE: _text(cells.get(t.COL_PHONE)),
            t.COL_RECEIVED_ON: dates[t.COL_RECEIVED_ON],
            t.COL_PICKUP_ON: dates[t.COL_PICKUP_ON],
            t.COL_BANQUET_ON: dates[t.COL_BANQUET_ON],
            t.COL_COUPLE_NAMES: _text(cells.get(t.COL_COUPLE_NAMES)),
            t.COL_TAKEN_BY: _text(cells.get(t.COL_TAKEN_BY)),
        },
        product=product,
        quantity=quantity,
        note=_text(cells.get(t.COL_NOTE)),
        cancelled=status == t.STATUS_CANCELLED,
    )


def _order_errors(order_no: str, rows: list[_Row]) -> list[Finding]:
    """Order-level problems that drop the whole 喜餅訂單."""
    errors: list[Finding] = []
    diffs: list[tuple[str, tuple[Any, ...]]] = []
    for column in _COMPARED_COLUMNS:
        seen: dict[Any, Any] = {}
        for r in rows:
            value = r.fields[column]
            seen.setdefault(_comparable(column, value), value)
        if len(seen) > 1:
            diffs.append((column, tuple(seen.values())))
    if diffs:
        errors.append(
            Finding(
                FindingKind.INCONSISTENT_ORDER_FIELDS,
                Severity.ERROR,
                group_rows((r.sheet, r.row) for r in rows),
                (order_no,),
                {"diffs": tuple(diffs)},
            )
        )

    by_product: dict[str, list[_Row]] = {}
    for r in rows:
        by_product.setdefault(r.product.code, []).append(r)
    for same in by_product.values():
        if len(same) > 1:
            errors.append(
                Finding(
                    FindingKind.DUPLICATE_PRODUCT,
                    Severity.ERROR,
                    group_rows((r.sheet, r.row) for r in same),
                    (order_no,),
                    {"product": same[0].product.name},
                )
            )
    return errors


def _comparable(column: str, value: Any) -> Any:
    if isinstance(value, str):
        if column == t.COL_PHONE and (digits := phone_digits(value)):
            return digits
        return re.sub(r"\s", "", unicodedata.normalize("NFKC", value))
    return value


def _order(order_no: str, rows: list[_Row]) -> ParsedOrder:
    f = rows[0].fields
    return ParsedOrder(
        order_no=order_no,
        orderer_name=f[t.COL_ORDERER_NAME],
        phone=f[t.COL_PHONE],
        received_on=f[t.COL_RECEIVED_ON],
        pickup_on=f[t.COL_PICKUP_ON],
        banquet_on=f[t.COL_BANQUET_ON],
        couple_names=f[t.COL_COUPLE_NAMES],
        taken_by=f[t.COL_TAKEN_BY],
        lines=tuple(
            ParsedLine(
                sheet=r.sheet,
                row=r.row,
                product_code=r.product.code,
                product_name=r.product.name,
                quantity=r.quantity,
                note=r.note,
                cancelled=r.cancelled,
            )
            for r in rows
        ),
    )


# ---------------------------------------------------------------- values

_YMD = re.compile(r"^(\d{2,4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})日?$")
_COMPACT = re.compile(r"^(\d{3,4})(\d{2})(\d{2})$")  # 20261025, 1151025
_MD = re.compile(r"^(\d{1,2})[/\-.月](\d{1,2})日?$")
_TIME_SUFFIX = re.compile(r"\s+\d{1,2}:\d{2}(:\d{2})?$")
_WEEKDAY_SUFFIX = re.compile(r"\s*\((週|星期)?[一二三四五六日天]\)$")
# Excel serial day numbers that land in a plausible range for this business.
_SERIAL_RANGE = (date(2000, 1, 1), date(2100, 1, 1))
_ROC_OFFSET = 1911


def parse_date(value: Any, today: date) -> date | None:
    """Excel date, Excel serial number, 西元 (2026/10/25), 民國 (115/10/25, 115年10月25日),
    or month/day (10/25, year nearest to `today`). None when it isn't a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            serial = from_excel(value)
        except (ValueError, OverflowError, TypeError):
            return None
        d = serial.date() if isinstance(serial, datetime) else serial
        return d if isinstance(d, date) and _SERIAL_RANGE[0] <= d < _SERIAL_RANGE[1] else None

    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = _WEEKDAY_SUFFIX.sub("", _TIME_SUFFIX.sub("", text)).replace(" ", "")
    if m := _YMD.match(text) or _COMPACT.match(text):
        year, month, day = (int(g) for g in m.groups())
        if year < _ROC_OFFSET:
            if len(m.group(1)) == 4:
                return None
            year += _ROC_OFFSET
        return _safe_date(year, month, day)
    if m := _MD.match(text):
        month, day = int(m.group(1)), int(m.group(2))
        candidates = [d for y in (today.year - 1, today.year, today.year + 1) if (d := _safe_date(y, month, day))]
        return min(candidates, key=lambda d: abs(d - today), default=None)
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


_QUANTITY_TEXT = re.compile(r"^\d{1,3}(,\d{3})*$|^\d+$")


def parse_quantity(value: Any) -> int | None:
    """A positive whole number of 盒 (120, 120.0, "120", "120盒"); None otherwise."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        quantity = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        quantity = int(value)
    else:
        text = unicodedata.normalize("NFKC", str(value)).strip().removesuffix("盒").strip()
        if not _QUANTITY_TEXT.match(text):
            return None
        quantity = int(text.replace(",", ""))
    return quantity if quantity > 0 else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _display_text(value: Any) -> str | None:
    """A cell value the way the 門市 sees it, for quoting back in the reply."""
    if isinstance(value, datetime | date):
        return f"{value.year}/{value.month:02d}/{value.day:02d}"
    return _text(value)


