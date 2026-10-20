"""The 對照表: per mock file, what was seeded and how the system should reply.

Tickets 04 (row checks), 06 (change detection), 07 (pending review) and 10
(historical import) turn this into tests. Match on the structured fields
(kind, sheet, rows, order_nos, change kinds, outcome); `reply` is the plain
繁中 wording store staff should see, a guide for the reply generator rather
than an exact string to assert.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from bakery.changes import KIND_LABELS
from bakery.models import ChangeKind


class Seeded(StrEnum):
    """Typical store mistakes deliberately mixed into day-1 files.

    The first seven are the ones ticket 01 requires every run to contain.
    """

    MISSING_ORDER_NO = "missing_order_no"  # 漏單號
    ROC_DATE = "roc_date"  # 日期用民國年
    PRODUCT_ALIAS = "product_alias"  # 品項用別名
    INCONSISTENT_ORDER_FIELDS = "inconsistent_order_fields"  # 同單號訂單層欄位不一致
    PICKUP_IN_PAST = "pickup_in_past"  # 取貨日已經過了
    EXTRA_COLUMN = "extra_column"  # 多了自己加的欄位
    MEMO_SHEET = "memo_sheet"  # 多了「備忘」分頁
    # Extras so ticket 04 has a fixture for every check it implements.
    INVALID_QUANTITY = "invalid_quantity"
    UNKNOWN_PRODUCT = "unknown_product"
    UNPARSEABLE_DATE = "unparseable_date"
    PICKUP_TOO_SOON = "pickup_too_soon"
    QUANTITY_OVER_THRESHOLD = "quantity_over_threshold"
    PHONE_FORMAT = "phone_format"
    DUPLICATE_PHONE_PICKUP = "duplicate_phone_pickup"
    REORDERED_COLUMNS = "reordered_columns"
    HEADER_SYNONYM = "header_synonym"


REQUIRED_SEEDED: tuple[Seeded, ...] = (
    Seeded.MISSING_ORDER_NO,
    Seeded.ROC_DATE,
    Seeded.PRODUCT_ALIAS,
    Seeded.INCONSISTENT_ORDER_FIELDS,
    Seeded.PICKUP_IN_PAST,
    Seeded.EXTRA_COLUMN,
    Seeded.MEMO_SHEET,
)

SEEDED_LABELS: dict[Seeded, str] = {
    Seeded.MISSING_ORDER_NO: "漏單號",
    Seeded.ROC_DATE: "日期用民國年",
    Seeded.PRODUCT_ALIAS: "品項用別名",
    Seeded.INCONSISTENT_ORDER_FIELDS: "同一個單號的各列，訂單層欄位不一致",
    Seeded.PICKUP_IN_PAST: "取貨日已經過了",
    Seeded.EXTRA_COLUMN: "多了一個自己加的欄位",
    Seeded.MEMO_SHEET: "多了一個「備忘」分頁",
    Seeded.INVALID_QUANTITY: "盒數不是正整數",
    Seeded.UNKNOWN_PRODUCT: "品項不在清單裡",
    Seeded.UNPARSEABLE_DATE: "日期看不懂",
    Seeded.PICKUP_TOO_SOON: "取貨日離今天太近",
    Seeded.QUANTITY_OVER_THRESHOLD: "盒數超過門檻",
    Seeded.PHONE_FORMAT: "電話格式異常",
    Seeded.DUPLICATE_PHONE_PICKUP: "同一支電話、同一個取貨日重複下單",
    Seeded.REORDERED_COLUMNS: "欄位順序跟範本不同",
    Seeded.HEADER_SYNONYM: "欄名用同義的寫法",
}


class Severity(StrEnum):
    ERROR = "error"  # the row (or whole order) is not accepted
    WARNING = "warning"  # accepted, but pointed out
    INFO = "info"  # file-level notice, e.g. a skipped sheet


class FindingKind(StrEnum):
    MISSING_ORDER_NO = "missing_order_no"
    INVALID_QUANTITY = "invalid_quantity"
    UNKNOWN_PRODUCT = "unknown_product"
    UNPARSEABLE_DATE = "unparseable_date"
    INCONSISTENT_ORDER_FIELDS = "inconsistent_order_fields"
    PICKUP_IN_PAST = "pickup_in_past"
    PICKUP_TOO_SOON = "pickup_too_soon"
    QUANTITY_OVER_THRESHOLD = "quantity_over_threshold"
    PHONE_FORMAT = "phone_format"
    DUPLICATE_PHONE_PICKUP = "duplicate_phone_pickup"
    SKIPPED_SHEET = "skipped_sheet"


class ToleranceKind(StrEnum):
    """Deviations the parser must absorb silently (no error, no reply line)."""

    ROC_DATE = "roc_date"
    PRODUCT_ALIAS = "product_alias"
    EXTRA_COLUMN = "extra_column"
    REORDERED_COLUMNS = "reordered_columns"
    HEADER_SYNONYM = "header_synonym"


class Outcome(StrEnum):
    APPLIED = "applied"  # takes effect immediately
    PENDING = "pending"  # becomes 待確認, previous content stays in force


@dataclass
class Finding:
    kind: FindingKind
    severity: Severity
    sheet: str | None
    rows: list[int]  # Excel row numbers; empty for file-level findings
    order_nos: list[str]  # 單號 involved; empty when there is none (e.g. 漏單號)
    reply: str


@dataclass
class Tolerance:
    kind: ToleranceKind
    sheet: str
    rows: list[int]  # empty for header-level tolerances
    detail: dict[str, str]  # e.g. {"寫法": "龍鳳餅", "應解析為": "龍鳳喜餅"}


@dataclass
class FieldDiff:
    field: str  # template column name, e.g. 盒數 / 取貨日 / 新人姓名 / 電話
    old: str
    new: str
    product: str | None = None  # set for line-level diffs (盒數, 狀態, 新品項)


@dataclass
class ChangeExpectation:
    order_no: str
    kinds: list[ChangeKind]
    diffs: list[FieldDiff]
    past_cutoff: bool
    outcome: Outcome
    reply: str


@dataclass
class FileExpectation:
    file: str  # path relative to the output directory
    stage: str  # day1 / day2
    store_code: str
    upload_on: str  # ISO date the file is uploaded in the demo timeline
    process_after: list[str]  # files that must be processed first, in order
    seeded: list[Seeded]
    accepted_orders: list[str]  # 單號 of orders that end up recorded from this file
    accepted_lines: int
    rejected_orders: list[str]  # whole orders refused (single-line orders refused by a row error included)
    rejected_rows: list[int]  # every Excel row not accepted
    findings: list[Finding]
    tolerances: list[Tolerance]
    reply_summary: str
    new_orders: list[str] = field(default_factory=list)
    changes: list[ChangeExpectation] = field(default_factory=list)
    unchanged_orders: list[str] = field(default_factory=list)  # identical: no action, no reply line
    absent_orders: list[str] = field(default_factory=list)  # recorded before, not in file: no action (ADR 0001)


@dataclass
class LegacyOrder:
    """One order the FDE conversion tool should produce from a legacy file."""

    source_sheet: str
    source_rows: list[int]
    orderer_name: str
    phone: str
    received_on: str
    pickup_on: str
    lines: dict[str, int]  # canonical 品項 name -> 盒數


@dataclass
class LegacyExpectation:
    file: str
    store_code: str
    layout: str  # how this legacy format differs from the 範本
    orders: list[LegacyOrder]
    notes: list[str]


@dataclass
class ReturningCustomer:
    """A phone that shows up in several orders (possibly typed differently)."""

    phone_digits: str  # normalized form ticket 09 should arrive at
    appearances: list[dict[str, str]]  # file, ref (單號 or source rows), orderer_name, phone_as_typed
    note: str


@dataclass
class Manifest:
    seed: int
    today: str  # day 1 (ISO)
    day2: str
    assumptions: dict[str, int]
    templates: list[str]
    files: list[FileExpectation]
    legacy: list[LegacyExpectation]
    returning_customers: list[ReturningCustomer]

    def file(self, relpath: str) -> FileExpectation:
        for f in self.files:
            if f.file == relpath:
                return f
        raise KeyError(relpath)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"


_SEVERITY_LABELS = {Severity.ERROR: "錯誤（不收）", Severity.WARNING: "警告（照收）", Severity.INFO: "提醒"}
_OUTCOME_LABELS = {Outcome.APPLIED: "直接生效", Outcome.PENDING: "待確認"}


def _rows_text(sheet: str | None, rows: list[int]) -> str:
    if not rows:
        return "整份檔案"
    return f"{sheet} 第 {'、'.join(str(r) for r in rows)} 列"


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(m: Manifest) -> str:
    out: list[str] = []
    w = out.append
    w("# 模擬資料對照表")
    w("")
    w("> 由 `uv run generate-mock-data` 產生，請勿手動修改。")
    w(f"> seed = {m.seed}；第一天 = {m.today}；第二天 = {m.day2}。日期都由第一天往前後推算。")
    w("")
    w("後面的 ticket 拿這份表當驗收依據：比對「類型、位置、單號、修改類型、結果」，")
    w("「系統應回覆」是給門市看的白話寫法，回覆文字照這個意思寫，不必一字不差。")
    w("同一份資料的機器可讀版本在 `expectations.json`。")
    w("")
    w("## 假設的設定值")
    w("")
    w("| 設定 | 值 |")
    w("|---|---|")
    labels = {
        "cutoff_days": "修改截止點（取貨日前幾天）",
        "pickup_too_soon_days": "取貨日離上傳日幾天以內算太近（含當天）",
        "quantity_warning_over": "一筆訂單明細超過幾盒要警告",
    }
    for key, value in m.assumptions.items():
        w(f"| {labels.get(key, key)} | {value} |")
    w("")
    w("其他隨機補上的訂單（表裡沒有列出的），取貨日都在第一天的 12～60 天後、每筆 20～200 盒、電話不重複，")
    w("所以不會觸發上面這些警告。")
    w("")
    w("## 範本")
    w("")
    for path in m.templates:
        w(f"- `{path}`")
    w("")

    for stage, title in (("day1", "第一天：各門市上傳"), ("day2", "第二天：修改與重傳")):
        w(f"## {title}")
        w("")
        for f in (f for f in m.files if f.stage == stage):
            w(f"### `{f.file}`")
            w("")
            w(f"- 門市：{f.store_code}；上傳日：{f.upload_on}")
            if f.process_after:
                w(f"- 要先處理：{'、'.join(f'`{p}`' for p in f.process_after)}")
            if f.seeded:
                w(f"- 混進的狀況：{'、'.join(SEEDED_LABELS[s] for s in f.seeded)}")
            w(f"- 回覆摘要：{f.reply_summary}")
            w(f"- 收下的單號：{'、'.join(f.accepted_orders) or '（無）'}（共 {f.accepted_lines} 筆訂單明細）")
            if f.rejected_orders or f.rejected_rows:
                w(f"- 不收：單號 {'、'.join(f.rejected_orders) or '（無）'}；列 {'、'.join(map(str, f.rejected_rows))}")
            if f.new_orders and stage == "day2":
                w(f"- 新單：{'、'.join(f.new_orders)}")
            if f.unchanged_orders:
                w(f"- 沒變（不做事、回覆不提）：{'、'.join(f.unchanged_orders)}")
            if f.absent_orders:
                w(f"- 這次檔案裡沒有、但之前收過（不做事，不算取消）：{'、'.join(f.absent_orders)}")
            w("")
            if f.findings:
                w("| 類型 | 嚴重度 | 位置 | 單號 | 系統應回覆 |")
                w("|---|---|---|---|---|")
                for fd in f.findings:
                    w(
                        f"| `{fd.kind}` | {_SEVERITY_LABELS[fd.severity]} | {_rows_text(fd.sheet, fd.rows)} "
                        f"| {'、'.join(fd.order_nos) or '—'} | {_md_cell(fd.reply)} |"
                    )
                w("")
            if f.changes:
                w("| 單號 | 修改類型 | 內容 | 過截止點 | 結果 | 系統應回覆 |")
                w("|---|---|---|---|---|---|")
                for c in f.changes:
                    kinds = "＋".join(KIND_LABELS[k] for k in c.kinds)
                    diffs = "；".join(
                        f"{d.product + ' ' if d.product else ''}{d.field} {d.old}→{d.new}" for d in c.diffs
                    )
                    w(
                        f"| {c.order_no} | {kinds} | {_md_cell(diffs)} | {'是' if c.past_cutoff else '否'} "
                        f"| {_OUTCOME_LABELS[c.outcome]} | {_md_cell(c.reply)} |"
                    )
                w("")
            if f.tolerances:
                w("照常處理、不用回報：")
                w("")
                for tol in f.tolerances:
                    detail = "，".join(f"{k}：{v}" for k, v in tol.detail.items())
                    where = _rows_text(tol.sheet, tol.rows) if tol.rows else f"{tol.sheet} 標題列"
                    w(f"- `{tol.kind}`（{where}）{detail}")
                w("")

    w("## 舊格式檔（歷史資料匯入用）")
    w("")
    for lg in m.legacy:
        w(f"### `{lg.file}`")
        w("")
        w(f"- 門市：{lg.store_code}")
        w(f"- 格式：{lg.layout}")
        for note in lg.notes:
            w(f"- {note}")
        w(f"- 轉換後應得到 {len(lg.orders)} 張喜餅訂單、{sum(len(o.lines) for o in lg.orders)} 筆訂單明細：")
        w("")
        w("| 來源 | 訂購人 | 電話 | 接單日 | 取貨日 | 品項與盒數 |")
        w("|---|---|---|---|---|---|")
        for o in lg.orders:
            items = "、".join(f"{name} {qty} 盒" for name, qty in o.lines.items())
            w(
                f"| {_rows_text(o.source_sheet, o.source_rows)} | {o.orderer_name} | {o.phone} "
                f"| {o.received_on} | {o.pickup_on} | {items} |"
            )
        w("")

    w("## 回頭客（客人資料用）")
    w("")
    w("| 電話（正規化後） | 出現在 | 說明 |")
    w("|---|---|---|")
    for rc in m.returning_customers:
        where = "；".join(
            f"`{a['file']}` {a['ref']}（{a['orderer_name']}，寫成 {a['phone_as_typed']}）" for a in rc.appearances
        )
        w(f"| {rc.phone_digits} | {_md_cell(where)} | {rc.note} |")
    w("")
    return "\n".join(out)
