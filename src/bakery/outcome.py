"""Structured result of processing one 上傳: what reply text is rendered from.

Findings and changes carry facts (kind, location, values), never wording:
`bakery.reply` is the one place that turns them into 繁中 text.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from bakery.models import ChangeDecision, ChangeField, ChangeKind


class Severity(StrEnum):
    ERROR = "error"  # the row (or the whole 喜餅訂單) is not accepted
    WARNING = "warning"  # accepted, but pointed out
    INFO = "info"  # file-level notice, e.g. a skipped sheet


class FindingKind(StrEnum):
    # Errors: the row is dropped.
    MISSING_ORDER_NO = "missing_order_no"
    MISSING_DATE = "missing_date"  # detail: column
    UNPARSEABLE_DATE = "unparseable_date"  # detail: column, value
    INVALID_QUANTITY = "invalid_quantity"  # detail: value (None when blank)
    UNKNOWN_PRODUCT = "unknown_product"  # detail: value (None when blank)
    INVALID_STATUS = "invalid_status"  # detail: value
    # Errors: the whole 喜餅訂單 is dropped.
    INCONSISTENT_ORDER_FIELDS = "inconsistent_order_fields"  # detail: diffs ((column, values), ...)
    DUPLICATE_PRODUCT = "duplicate_product"  # detail: product
    # Warnings: accepted.
    PICKUP_IN_PAST = "pickup_in_past"  # detail: pickup_on
    PICKUP_TOO_SOON = "pickup_too_soon"  # detail: pickup_on, days
    QUANTITY_OVER_THRESHOLD = "quantity_over_threshold"  # detail: product, quantity
    PHONE_FORMAT = "phone_format"  # detail: phone, problem (PhoneProblem)
    DUPLICATE_PHONE_PICKUP = "duplicate_phone_pickup"  # detail: stored_order_nos
    # Info.
    SKIPPED_SHEET = "skipped_sheet"  # detail: reason (SkipReason), other_store_code


class SkipReason(StrEnum):
    NOT_TEMPLATE = "not_template"  # headers don't match the 範本
    OTHER_STORE = "other_store"  # a 範本 sheet whose 門市代碼 differs from the file's


@dataclass(frozen=True)
class SheetRows:
    """Where a finding points: a sheet and its Excel row numbers (empty = whole sheet)."""

    sheet: str
    rows: tuple[int, ...] = ()


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    severity: Severity
    locations: tuple[SheetRows, ...]
    order_nos: tuple[str, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)


class FailureKind(StrEnum):
    """The whole file is refused; nothing in it is stored except the original."""

    UNREADABLE_FILE = "unreadable_file"
    NO_ORDER_SHEET = "no_order_sheet"
    MISSING_STORE_CODE = "missing_store_code"
    UNKNOWN_STORE = "unknown_store"  # detail: store_code
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    detail: Mapping[str, Any] = field(default_factory=dict)


class UploaderNoticeKind(StrEnum):
    """What the reply's first line says about the 傳檔者 and their 門市綁定."""

    NEW_BINDING = "new_binding"  # first file from this account: bound to the file's 門市, pending
    OTHER_STORE = "other_store"  # bound to another 門市 than the file's
    UNIDENTIFIED = "unidentified"  # LINE did not say which account sent the file


@dataclass(frozen=True)
class UploaderNotice:
    kind: UploaderNoticeKind
    store_name: str | None = None  # the file's 門市 (NEW_BINDING, OTHER_STORE)
    bound_store_name: str | None = None  # the 門市 the account is bound to (OTHER_STORE)


@dataclass(frozen=True)
class FieldDiff:
    """One field of a 修改, old → new as the change log stores it (see bakery.models.ChangeEntry).
    `kind` is the 修改類型 this field contributes (None for a 新單). Line fields name
    their 品項 and carry the line's 盒數 in this file."""

    field: ChangeField
    old: str | None
    new: str | None
    kind: ChangeKind | None = None
    product_code: str | None = None
    product_name: str | None = None
    quantity: int | None = None


@dataclass(frozen=True)
class OrderChange:
    """A 喜餅訂單 already on record that came in with different content."""

    order_no: str
    kinds: tuple[ChangeKind, ...]
    diffs: tuple[FieldDiff, ...]
    decision: ChangeDecision


@dataclass(frozen=True)
class UploadOutcome:
    store_code: str | None
    store_name: str | None
    order_count: int  # 喜餅訂單 received in this file
    line_count: int  # 訂單明細 received in this file
    rejected_rows: tuple[SheetRows, ...] = ()  # rows not accepted, per sheet
    findings: tuple[Finding, ...] = ()
    failure: Failure | None = None
    new_order_nos: tuple[str, ...] = ()  # 單號 seen for the first time
    unchanged_order_nos: tuple[str, ...] = ()  # on record with identical content: never mentioned
    changes: tuple[OrderChange, ...] = ()
    uploader_notice: UploaderNotice | None = None  # only for files whose 門市 is known

    @property
    def rejected_row_count(self) -> int:
        return sum(len(s.rows) for s in self.rejected_rows)


@dataclass(frozen=True)
class ProcessResult:
    upload_id: int
    reply_text: str  # exactly what the LINE reply says (capped at the LINE limit)
    report_text: str  # the full reply, every finding listed; shown on the web
    outcome: UploadOutcome
