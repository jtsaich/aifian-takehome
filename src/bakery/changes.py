"""修改: compare a 喜餅訂單 on record with the same 單號 in a new 上傳, classify the
difference into 修改類型, decide whether it applies now, and apply it.

ADR 0001: only what the file contains is compared. A 訂單明細 on record that the
file doesn't list is left alone (it is not a 取消); 取消 is only ever the 狀態 column.
Values are compared and logged as text: dates ISO, 盒數 digits, 狀態 a LineStatus value.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from bakery import template as t
from bakery.models import ChangeDecision, ChangeField, ChangeKind, LineStatus, Order, OrderLine
from bakery.outcome import FieldDiff
from bakery.parsing import ParsedLine, ParsedOrder
from bakery.phone import normalize_phone

# Order-level fields in 範本 column order. Every ChangeField value is also the attribute
# name on Order / OrderLine and, for order fields, on ParsedOrder.
ORDER_FIELDS: tuple[ChangeField, ...] = (
    ChangeField.ORDERER_NAME,
    ChangeField.PHONE,
    ChangeField.RECEIVED_ON,
    ChangeField.PICKUP_ON,
    ChangeField.BANQUET_ON,
    ChangeField.COUPLE_NAMES,
    ChangeField.TAKEN_BY,
)
DATE_FIELDS = frozenset({ChangeField.RECEIVED_ON, ChangeField.PICKUP_ON, ChangeField.BANQUET_ON})

FIELD_LABELS: dict[ChangeField, str] = {
    ChangeField.ORDERER_NAME: t.COL_ORDERER_NAME,
    ChangeField.PHONE: t.COL_PHONE,
    ChangeField.RECEIVED_ON: t.COL_RECEIVED_ON,
    ChangeField.PICKUP_ON: t.COL_PICKUP_ON,
    ChangeField.BANQUET_ON: t.COL_BANQUET_ON,
    ChangeField.COUPLE_NAMES: t.COL_COUPLE_NAMES,
    ChangeField.TAKEN_BY: t.COL_TAKEN_BY,
    ChangeField.QUANTITY: t.COL_QUANTITY,
    ChangeField.NOTE: t.COL_NOTE,
    ChangeField.STATUS: t.COL_STATUS,
}

KIND_LABELS: dict[ChangeKind, str] = {
    ChangeKind.ADD_QTY: "追加",
    ChangeKind.REDUCE_QTY: "減量",
    ChangeKind.PICKUP_DATE: "改取貨日",
    ChangeKind.CANCEL: "取消",
    ChangeKind.INFO_FIX: "資料更正",
    ChangeKind.SUSPECTED_REUSE: "疑似單號重複使用",
}

# 影響生產的修改.
PRODUCTION_KINDS = frozenset(
    {ChangeKind.ADD_QTY, ChangeKind.REDUCE_QTY, ChangeKind.PICKUP_DATE, ChangeKind.CANCEL}
)


@dataclass(frozen=True)
class Detected:
    kinds: tuple[ChangeKind, ...]  # in ChangeKind order
    diffs: tuple[FieldDiff, ...]  # order fields in column order, then lines in file order


def is_suspected_reuse(kinds: Iterable[ChangeKind]) -> bool:
    """疑似單號重複使用: it always stands alone (detect_change), and the whole 修改 waits."""
    return tuple(kinds) == (ChangeKind.SUSPECTED_REUSE,)


def new_order_diffs(parsed: ParsedOrder) -> tuple[FieldDiff, ...]:
    """A 新單 as change log entries from nothing: what apply_diffs builds the order from."""
    diffs = [
        FieldDiff(f, None, encode(value))
        for f in ORDER_FIELDS
        if (value := getattr(parsed, f.value)) is not None
    ]
    for line in parsed.lines:
        diffs.extend(_line_diffs(None, line, kind=None))
    return tuple(diffs)


def detect_change(order: Order, parsed: ParsedOrder) -> Detected | None:
    """None when the file says nothing new about `order` (an identical re-send)."""
    diffs: list[FieldDiff] = []
    for f in ORDER_FIELDS:
        old, new = getattr(order, f.value), getattr(parsed, f.value)
        if old == new or (f is ChangeField.PHONE and _same_phone(old, new)):
            continue
        kind = ChangeKind.PICKUP_DATE if f is ChangeField.PICKUP_ON else ChangeKind.INFO_FIX
        diffs.append(FieldDiff(f, encode(old), encode(new), kind))

    stored = {line.product_code: line for line in order.lines}
    for line in parsed.lines:
        old_line = stored.get(line.product_code)
        diffs.extend(_line_diffs(old_line, line, kind=_line_kind(old_line, line)))

    if not diffs:
        return None
    kinds = {d.kind for d in diffs}
    if _suspected_reuse(diffs):
        return Detected((ChangeKind.SUSPECTED_REUSE,), tuple(diffs))
    return Detected(tuple(k for k in ChangeKind if k in kinds), tuple(diffs))


def _suspected_reuse(diffs: Sequence[FieldDiff]) -> bool:
    """GLOSSARY 疑似單號重複使用: the phone changed, and so did the set of 品項 (one added,
    取消, or back from 取消) or the 取貨日. A phone change with only other 盒數 is a
    資料更正 plus 追加 / 減量, classified as usual."""
    phone_changed = any(
        d.field is ChangeField.PHONE and d.old is not None and d.new is not None for d in diffs
    )
    pickup_changed = any(d.field is ChangeField.PICKUP_ON for d in diffs)
    products_changed = any(
        d.product_code is not None
        and d.kind in PRODUCTION_KINDS
        and (d.field is ChangeField.STATUS or (d.field is ChangeField.QUANTITY and d.old is None))
        for d in diffs
    )
    return phone_changed and (pickup_changed or products_changed)


def past_cutoff(pickup_on: date, today: date, cutoff_days: int) -> bool:
    """修改截止點: 取貨日前 N 天. That day is the last on which a change applies directly;
    from the next day on (fewer than N days left before 取貨日) it is past the cutoff.
    With N = 7 and 取貨日 11/28: sent on 11/21 applies, sent on 11/22 waits for 總部."""
    return (pickup_on - today).days < cutoff_days


def decide(
    detected: Detected, order: Order, *, today: date, cutoff_days: int, historical: bool = False
) -> ChangeDecision:
    """The one rule for whether a change to `order` applies now or waits for 總部 (待確認).

    - A 歷史資料匯入 (`historical`) always applies: it records what already happened,
      affects no production, and nothing in it waits for 總部.
    - 疑似單號重複使用 never applies on its own, whatever the date: it may be two
      different orders sharing one 單號, and applying would overwrite the first one.
    - A change that affects production waits once past the 修改截止點 of the earlier of
      the 取貨日 on record and the new one: postponing a near 取貨日 and pulling a far
      one near both wait. 資料更正 always applies: merge splits a held 修改's 資料更正
      off with split_info_fix and applies it at once; only the production part waits.
    """
    if historical:
        return ChangeDecision.APPLIED
    if ChangeKind.SUSPECTED_REUSE in detected.kinds:
        return ChangeDecision.HELD
    if PRODUCTION_KINDS.isdisjoint(detected.kinds):
        return ChangeDecision.APPLIED
    pickups = [order.pickup_on]
    pickups += [date.fromisoformat(d.new) for d in detected.diffs if d.field is ChangeField.PICKUP_ON]
    if past_cutoff(min(pickups), today, cutoff_days):
        return ChangeDecision.HELD
    return ChangeDecision.APPLIED


def split_info_fix(detected: Detected) -> tuple[Detected, Detected] | None:
    """A held 修改 that also carries 資料更正: (the 資料更正 part, which applies now, and
    the production part, which waits). None when there is nothing to split off: no
    資料更正, or a suspected reused 單號, whose content waits as a whole."""
    if ChangeKind.SUSPECTED_REUSE in detected.kinds or ChangeKind.INFO_FIX not in detected.kinds:
        return None
    info = tuple(d for d in detected.diffs if d.kind is ChangeKind.INFO_FIX)
    production = tuple(d for d in detected.diffs if d.kind is not ChangeKind.INFO_FIX)
    if not production:
        return None
    return (
        Detected((ChangeKind.INFO_FIX,), info),
        Detected(tuple(k for k in detected.kinds if k is not ChangeKind.INFO_FIX), production),
    )


def apply_diffs(order: Order, diffs: Iterable[FieldDiff]) -> None:
    """Write each diff's new value onto `order`, adding 訂單明細 it doesn't have yet."""
    lines = {line.product_code: line for line in order.lines}
    for d in diffs:
        value = decode(d.field, d.new)
        if d.product_code is None:
            setattr(order, d.field.value, value)
            continue
        line = lines.get(d.product_code)
        if line is None:
            line = lines[d.product_code] = OrderLine(
                product_code=d.product_code, status=LineStatus.ACTIVE
            )
            order.lines.append(line)
        setattr(line, d.field.value, value)


def encode(value: str | int | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def decode(field: ChangeField, text: str | None) -> str | int | date | LineStatus | None:
    if text is None:
        return None
    if field in DATE_FIELDS:
        return date.fromisoformat(text)
    if field is ChangeField.QUANTITY:
        return int(text)
    if field is ChangeField.STATUS:
        return LineStatus(text)
    return text


def show_value(field: ChangeField, text: str | None) -> str:
    """A change log value as pages and downloads show it ("" for empty)."""
    if text is None:
        return ""
    if field in DATE_FIELDS:
        return text.replace("-", "/")
    if field is ChangeField.STATUS:
        return "取消" if text == LineStatus.CANCELLED else "（空白）"
    return text


def _same_phone(old: str | None, new: str | None) -> bool:
    """The same number written differently (0912-345-678 / 0912345678 / +886 912 345 678)."""
    if not old or not new:
        return False
    phone = normalize_phone(old)
    return phone is not None and phone == normalize_phone(new)


def _status(line: ParsedLine) -> LineStatus:
    return LineStatus.CANCELLED if line.cancelled else LineStatus.ACTIVE


def _line_diffs(
    old: OrderLine | None, line: ParsedLine, *, kind: ChangeKind | None
) -> list[FieldDiff]:
    """`kind` goes on 盒數 and 狀態; a 備註 change is a 資料更正 (None throughout for a 新單)."""

    def diff(field: ChangeField, before, after) -> FieldDiff:
        field_kind = ChangeKind.INFO_FIX if field is ChangeField.NOTE and kind is not None else kind
        return FieldDiff(
            field,
            encode(before),
            encode(after),
            field_kind,
            line.product_code,
            line.product_name,
            line.quantity,
        )

    status = _status(line)
    if old is None:
        diffs = [diff(ChangeField.QUANTITY, None, line.quantity)]
        if line.note is not None:
            diffs.append(diff(ChangeField.NOTE, None, line.note))
        if status is not LineStatus.ACTIVE:
            diffs.append(diff(ChangeField.STATUS, None, status))
        return diffs
    return [
        diff(f, before, after)
        for f, before, after in (
            (ChangeField.QUANTITY, old.quantity, line.quantity),
            (ChangeField.NOTE, old.note, line.note),
            (ChangeField.STATUS, old.status, status),
        )
        if before != after
    ]


def _line_kind(old: OrderLine | None, line: ParsedLine) -> ChangeKind:
    """How a changed 訂單明細 affects production: compares the 盒數 the kitchen makes."""
    if old is not None and old.status == LineStatus.ACTIVE and line.cancelled:
        return ChangeKind.CANCEL
    before = 0 if old is None or old.status == LineStatus.CANCELLED else old.quantity
    after = 0 if line.cancelled else line.quantity
    if after > before:
        return ChangeKind.ADD_QTY
    if after < before:
        return ChangeKind.REDUCE_QTY
    return ChangeKind.INFO_FIX  # 備註, or a line that stays 取消
