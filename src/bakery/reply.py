"""The one place that turns an UploadOutcome into the 繁中 reply the 傳檔者 reads.

The same text goes to the LINE group and to the 模擬群組上傳 page. Every
problem names its place (分頁 + Excel 列號) and says, in store language, what
to do; errors (not accepted) and warnings (accepted) are listed apart. Every
reply ends with the link to the 廚房彙總 page.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from bakery.changes import DATE_FIELDS, FIELD_LABELS, KIND_LABELS
from bakery.models import ChangeDecision, ChangeField, ChangeKind, LineStatus, ReviewStatus
from bakery.outcome import (
    Failure,
    FailureKind,
    FieldDiff,
    Finding,
    FindingKind,
    HeldChange,
    OrderChange,
    Severity,
    SkipReason,
    UploaderNotice,
    UploaderNoticeKind,
    UploadOutcome,
)
from bakery.phone import PhoneProblem

# LINE text messages hold at most 5,000 characters.
LINE_TEXT_LIMIT = 5000
# Shown in errors about dates, as the format to follow.
DATE_EXAMPLE = "2026/11/08"
# Something broke on our side, not in the file. The webhook also sends it on its own
# when a file could not even be kept.
PROCESSING_FAILED = "這份檔案沒處理成功，總部已收到通知。"
# The 廚房彙總 page (bakery.web.routes.kitchen_summary), linked at the end of every reply.
KITCHEN_SUMMARY_PATH = "/kitchen"

_DECISIONS_TITLE = "【總部已處理您之前的待確認】"
_CHANGES_TITLE = "【修改】"
_REPEATED_TITLE = "【之前傳過的修改】"
_SECTIONS: tuple[tuple[Severity, str], ...] = (
    (Severity.ERROR, "【沒有收，請改好後再傳一次】"),
    (Severity.WARNING, "【已先收下，請再確認】"),
    (Severity.INFO, "【提醒】"),
)


@dataclass(frozen=True)
class Reply:
    text: str  # the LINE reply, at most LINE_TEXT_LIMIT characters
    report: str  # every finding, for the web page the long reply links to


def render_reply(outcome: UploadOutcome, report_url: str) -> Reply:
    """`report_url` is where the full list can be read when the LINE reply is cut short."""
    head = _summary(outcome)
    if outcome.uploader_notice is not None:
        head = f"{uploader_notice_text(outcome.uploader_notice)}\n{head}"
    if outcome.decisions:
        # 總部's decisions come first of all: the 門市 is told nowhere else (no push).
        decided = "".join(f"\n・{decision_text(d)}" for d in outcome.decisions)
        head = f"{_DECISIONS_TITLE}{decided}\n\n{head}"
    items = [(_CHANGES_TITLE, f"・{change_text(c)}") for c in outcome.changes]
    items += [(_REPEATED_TITLE, f"・{repeated_text(r)}") for r in outcome.repeated]
    items += [
        (title, f"・{finding_text(f)}")
        for severity, title in _SECTIONS
        for f in outcome.findings
        if f.severity == severity
    ]
    report = with_kitchen_summary_link(_join(head, items))
    if len(report) <= LINE_TEXT_LIMIT:
        return Reply(report, report)

    def cut(kept: int) -> str:
        rest = _rest(len(items) - kept, report_url)
        return with_kitchen_summary_link(_join(head, items[:kept]) + rest)

    kept = 0
    for k in range(1, len(items) + 1):
        if len(cut(k)) > LINE_TEXT_LIMIT:
            break
        kept = k
    return Reply(cut(kept), report)


def site_url(path: str) -> str:
    """Absolute when PUBLIC_BASE_URL is set (LINE needs a full link), else a site path."""
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") + path


def with_kitchen_summary_link(text: str) -> str:
    """`text` with the 廚房彙總 link as its last line, as every reply ends."""
    return f"{text}\n\n廚房彙總：{site_url(KITCHEN_SUMMARY_PATH)}"


def _join(head: str, items: list[tuple[str, str]]) -> str:
    parts = [head]
    current = None
    for title, line in items:
        if title != current:
            parts.append(f"\n\n{title}")
            current = title
        parts.append(f"\n{line}")
    return "".join(parts)


def _rest(count: int, report_url: str) -> str:
    return f"\n\n其餘 {count} 項請看網頁：{report_url}"


def _summary(outcome: UploadOutcome) -> str:
    if outcome.failure is not None and outcome.failure.kind == FailureKind.INTERNAL_ERROR:
        return PROCESSING_FAILED + "原檔已經保存，不用重傳。"
    if outcome.failure is not None:
        return f"這份檔案沒有收：{failure_text(outcome.failure)}"
    text = f"{outcome.store_name}（{outcome.store_code}）："
    if outcome.changes or outcome.unchanged_order_nos or outcome.repeated:
        text += _merge_summary(outcome)
    else:
        text += f"收到 {outcome.order_count} 張喜餅訂單、{outcome.line_count} 筆訂單明細。"
    if outcome.rejected_row_count:
        text += f"有 {outcome.rejected_row_count} 列沒有收，請改好後再傳一次。"
    warnings = sum(1 for f in outcome.findings if f.severity == Severity.WARNING)
    if warnings:
        text += f"有 {warnings} 個地方已先收下，請再確認。"
    return text


def uploader_notice_text(notice: UploaderNotice) -> str:
    """The reply's first line, about who sent the file and which 門市 they belong to."""
    match notice.kind:
        case UploaderNoticeKind.NEW_BINDING:
            return f"已記錄您為 {notice.store_name}（待總部確認）"
        case UploaderNoticeKind.OTHER_STORE:
            return (
                f"注意：您的帳號登記在{notice.bound_store_name}，這份是{notice.store_name}的檔案。"
                "已照常收下，請確認沒有傳錯檔案。"
            )
        case UploaderNoticeKind.UNIDENTIFIED:
            return "系統認不出是哪個 LINE 帳號傳的，檔案照常收下，但沒辦法記錄傳檔者。"
    raise AssertionError(notice.kind)


def _merge_summary(outcome: UploadOutcome) -> str:
    """For a file that repeats 單號 already on record; unchanged ones are not counted."""
    parts = []
    if outcome.new_order_nos:
        parts.append(f"新單 {len(outcome.new_order_nos)} 張")
    if outcome.changes:
        part = f"修改 {len(outcome.changes)} 張"
        held = sum(1 for c in outcome.changes if c.decision == ChangeDecision.HELD)
        if held:
            part += f"，其中 {held} 張待總部確認"
        parts.append(part)
    still_held = sum(1 for r in outcome.repeated if r.status == ReviewStatus.PENDING)
    if still_held:
        parts.append(f"{still_held} 張修改仍待總部確認")
    rejected = sum(1 for r in outcome.repeated if r.status == ReviewStatus.REJECTED)
    if rejected:
        parts.append(f"{rejected} 張修改已被總部退回")
    if not parts:
        return "這份檔案的內容之前都收過了，沒有新單，也沒有修改。"
    return "；".join(parts) + "。"


def change_text(c: OrderChange) -> str:
    """「單號 0101：追加，龍鳳喜餅 80→120 盒」: what changed, in store words."""
    if c.kinds == (ChangeKind.SUSPECTED_REUSE,):
        return f"單號 {c.order_no}：{_reuse_text(c.diffs)}"
    details = [text for kind in c.kinds for text in _kind_details(kind, c.diffs)]
    if c.kinds == (ChangeKind.PICKUP_DATE,):
        details = [_dates(_only(c.diffs, ChangeField.PICKUP_ON))]  # 改取貨日 already says what
    text = f"單號 {c.order_no}：{'＋'.join(KIND_LABELS[k] for k in c.kinds)}，{'；'.join(details)}"
    if c.decision == ChangeDecision.HELD:
        text += "（已過截止點，待總部確認）"  # held and not a reused 單號: the cutoff
    return text


def repeated_text(h: HeldChange) -> str:
    """A 待確認 sent again unchanged: 「單號 0101 龍鳳喜餅 盒數 120 仍待總部確認」, or
    already 退回 and what to write back so the reminder stops."""
    if h.kinds == (ChangeKind.SUSPECTED_REUSE,):
        if h.status == ReviewStatus.PENDING:
            return f"單號 {h.order_no}：電話不同的這份內容仍待總部確認，這張單先照舊。"
        return f"單號 {h.order_no}：電話不同的這份內容{_REUSE_REJECTED}"
    what, still = _held_parts(h.diffs)
    if h.status == ReviewStatus.PENDING:
        return f"單號 {h.order_no} {what} 仍待總部確認"
    return f"單號 {h.order_no} {what} 已被總部退回，{still}"


def decision_text(h: HeldChange) -> str:
    """總部 confirmed or 退回 a 待確認 since the 門市's last upload."""
    if h.kinds == (ChangeKind.SUSPECTED_REUSE,):
        if h.status == ReviewStatus.CONFIRMED:
            return f"單號 {h.order_no}：電話不同的那份內容，總部確認是同一張單，已改成新的內容。"
        return f"單號 {h.order_no}：電話不同的那份內容{_REUSE_REJECTED}"
    what, still = _held_parts(h.diffs)
    if h.status == ReviewStatus.CONFIRMED:
        return f"單號 {h.order_no} {what}：總部已確認，已照新的內容計算。"
    return f"單號 {h.order_no} {what}：總部已退回，{still}。"


_REUSE_REJECTED = (
    "已被總部退回，這個單號仍是原本那張單。請把 Excel 改回原本的內容；如果是另一位客人的單，請開新的單號再傳。"
)


def _held_parts(diffs: Sequence[FieldDiff]) -> tuple[str, str]:
    """The production side of a held 修改: what the file says, and (once 退回) what the
    system still counts and what to write back in Excel, part by part in the same order:
    「龍鳳喜餅 盒數 120」,「系統仍以 80 盒計算，請把 Excel 改回 80」."""
    parts: list[tuple[str, str, str]] = []
    for d in diffs:
        if d.field is ChangeField.PICKUP_ON:
            old = _date(date.fromisoformat(d.old))
            parts.append((f"取貨日 {_date(date.fromisoformat(d.new))}", f"取貨日 {old}", old))
    for line in _by_product([d for d in diffs if d.product_code]):
        name = line[0].product_name
        status = next((d for d in line if d.field is ChangeField.STATUS), None)
        quantity = next((d for d in line if d.field is ChangeField.QUANTITY), None)
        if status is not None and status.old is None:
            continue  # a new line already marked 取消: nothing to produce either way
        if status is not None and status.new == LineStatus.CANCELLED:
            parts.append((f"{name} 取消", f"{name} 照常生產", "狀態空白"))
        elif status is not None:
            parts.append((f"{name} 恢復生產", f"{name} 已取消", "狀態「取消」"))
        elif quantity is not None and quantity.old is None:
            parts.append((f"新增{name} {quantity.new} 盒", f"沒有{name}", f"沒有{name}"))
        elif quantity is not None:
            parts.append((f"{name} 盒數 {quantity.new}", f"{quantity.old} 盒", quantity.old))
    if not parts:  # held only for the cutoff, so never without a production part
        raise AssertionError("a held 修改 with nothing that affects production")
    what, counted, write_back = ("、".join(column) for column in zip(*parts, strict=True))
    gap = " " if counted[-1].isascii() else ""  # 「取貨日 2026/11/28 計算」, 「80 盒計算」
    return what, f"系統仍以 {counted}{gap}計算，請把 Excel 改回 {write_back}"


def _reuse_text(diffs: Sequence[FieldDiff]) -> str:
    pickup = any(d.field is ChangeField.PICKUP_ON for d in diffs)
    lines = [d for d in diffs if d.product_code and d.kind is not ChangeKind.INFO_FIX]
    what = []
    if pickup:
        what.append("取貨日")
    if lines:
        new_or_cancelled = any(d.old is None or d.field is ChangeField.STATUS for d in lines)
        what.append("品項" if new_or_cancelled else "盒數")
    return (
        f"電話跟之前不同，{'和'.join(what)}也變了，可能是兩張不同的單用了同一個單號。"
        "這張單先照舊，待總部確認；請檢查單號有沒有重複。"
    )


def _kind_details(kind: ChangeKind, diffs: Sequence[FieldDiff]) -> list[str]:
    mine = [d for d in diffs if d.kind is kind]
    match kind:
        case ChangeKind.ADD_QTY | ChangeKind.REDUCE_QTY:
            return [_quantity_detail(line) for line in _by_product(mine)]
        case ChangeKind.PICKUP_DATE:
            return [f"{FIELD_LABELS[d.field]} {_dates(d)}" for d in mine]
        case ChangeKind.CANCEL:
            boxes = "、".join(_cancelled_boxes(line) for line in _by_product(mine))
            return [f"{boxes}不再生產"]
        case ChangeKind.INFO_FIX:
            # A 狀態 entry here only accompanies a new line already marked 取消: said by its 盒數.
            return [_info_detail(d) for d in mine if d.field is not ChangeField.STATUS]
    raise AssertionError(kind)


def _cancelled_boxes(line: list[FieldDiff]) -> str:
    """The 盒數 on record that the kitchen no longer makes."""
    quantity = next((d for d in line if d.field is ChangeField.QUANTITY), None)
    boxes = quantity.old if quantity is not None else line[0].quantity
    return f"{line[0].product_name} {boxes} 盒"


def _quantity_detail(line: list[FieldDiff]) -> str:
    """追加/減量 of one 品項: a new one, one back from 取消, or a different 盒數."""
    name = line[0].product_name
    quantity = next((d for d in line if d.field is ChangeField.QUANTITY), None)
    if quantity is not None and quantity.old is None:
        return f"新增{name} {quantity.new} 盒"
    if any(d.field is ChangeField.STATUS for d in line):
        return f"{name} 恢復生產 {line[0].quantity} 盒"
    return f"{name} {quantity.old}→{quantity.new} 盒"


def _info_detail(d: FieldDiff) -> str:
    if d.field is ChangeField.PHONE:
        return "電話已更新"
    if d.field is ChangeField.QUANTITY:  # a line marked 取消 either way
        if d.old is None:
            return f"新增{d.product_name} {d.new} 盒（已標取消）"
        return f"{d.product_name}（已取消）{d.old}→{d.new} 盒"
    label = f"{d.product_name} {FIELD_LABELS[d.field]}" if d.product_code else FIELD_LABELS[d.field]
    return f"{label} {_dates(d) if d.field in DATE_FIELDS else _texts(d)}"


def _by_product(diffs: Sequence[FieldDiff]) -> list[list[FieldDiff]]:
    groups: dict[str, list[FieldDiff]] = {}
    for d in diffs:
        groups.setdefault(d.product_code, []).append(d)
    return list(groups.values())


def _only(diffs: Sequence[FieldDiff], field: ChangeField) -> FieldDiff:
    return next(d for d in diffs if d.field is field)


def _dates(d: FieldDiff) -> str:
    def show(text: str | None) -> str:
        return "空白" if text is None else _date(date.fromisoformat(text))

    return f"{show(d.old)}→{show(d.new)}"


def _texts(d: FieldDiff) -> str:
    return f"{d.old or '空白'}→{d.new or '空白'}"


def failure_text(failure: Failure) -> str:
    """Why the file was refused, for failures the 門市 can fix (not INTERNAL_ERROR)."""
    match failure.kind:
        case FailureKind.UNREADABLE_FILE:
            return "系統打不開這份檔案。請用喜餅訂單範本（.xlsx）存檔後再傳一次。"
        case FailureKind.NO_ORDER_SHEET:
            return (
                "檔案裡找不到喜餅訂單的欄位（單號、接單日、取貨日、品項、盒數）。"
                "請用喜餅訂單範本填寫後再傳一次。"
            )
        case FailureKind.MISSING_STORE_CODE:
            return "範本左上角的門市代碼是空的。請填上門市代碼後再傳一次。"
        case FailureKind.UNKNOWN_STORE:
            return (
                f"門市代碼「{failure.detail['store_code']}」不在門市清單裡。"
                "請確認範本左上角的門市代碼後再傳一次。"
            )
    raise AssertionError(failure.kind)


def finding_text(f: Finding) -> str:
    """One problem, in the words store staff read."""
    d = f.detail
    at = _at(f)
    match f.kind:
        case FindingKind.MISSING_ORDER_NO:
            return f"{at}：沒有填單號，這一列沒有收。請補上單號再傳一次。"
        case FindingKind.MISSING_DATE:
            return f"{at}：沒有填{d['column']}，這一列沒有收。請補上日期再傳一次。"
        case FindingKind.UNPARSEABLE_DATE:
            return (
                f"{at}：{d['column']}寫「{d['value']}」，系統看不懂，這一列沒有收。"
                f"請填像 {DATE_EXAMPLE} 這樣的日期。"
            )
        case FindingKind.INVALID_QUANTITY:
            filled = "沒有填" if d["value"] is None else f"填了 {_quoted_number(d['value'])}"
            return f"{at}：盒數{filled}，要填 1 以上的整數，這一列沒有收。"
        case FindingKind.UNKNOWN_PRODUCT:
            if d["value"] is None:
                return f"{at}：沒有填品項，這一列沒有收。請從清單選品項再傳一次。"
            return (
                f"{at}：品項「{d['value']}」不在商品清單裡，這一列沒有收。"
                "請改成清單上的品項；如果是新品項，請總部加進清單後再傳一次。"
            )
        case FindingKind.INVALID_STATUS:
            return (
                f"{at}：狀態寫「{d['value']}」，系統看不懂，這一列沒有收。"
                "要取消請選「取消」，其他時候狀態留空。"
            )
        case FindingKind.INCONSISTENT_ORDER_FIELDS:
            diffs = "、".join(
                f"{column}不一樣（{'、'.join(_value(v) for v in values)}）" for column, values in d["diffs"]
            )
            return (
                f"{at}：同一張單的{diffs}，整張單沒有收。"
                "同一張單的每一列，從單號到接單人都要填一樣；要分兩次取貨，請開兩個單號。"
            )
        case FindingKind.DUPLICATE_PRODUCT:
            return f"{at}：同一張單的{d['product']}寫了好幾列，整張單沒有收。同一個品項請合成一列。"
        case FindingKind.LIVE_ORDER_NO:
            return f"{at}：這個單號已經有上線後收到的喜餅訂單，歷史資料不會蓋過它，整張單沒有匯入。"
        case FindingKind.PICKUP_IN_PAST:
            return f"{at}：取貨日 {_date(d['pickup_on'])} 已經過了，已先收下，請確認日期有沒有打錯。"
        case FindingKind.PICKUP_TOO_SOON:
            left = "就是今天" if d["days"] == 0 else f"只剩 {d['days']} 天"
            return f"{at}：取貨日 {_date(d['pickup_on'])} {left}，已先收下，請確認中央廚房來得及做。"
        case FindingKind.QUANTITY_OVER_THRESHOLD:
            return (
                f"{at}：{d['product']} {d['quantity']} 盒比平常多很多，已先收下，"
                "請確認有沒有多打一個 0。"
            )
        case FindingKind.PHONE_FORMAT:
            looks = {
                PhoneProblem.TOO_SHORT: "好像少了幾碼",
                PhoneProblem.TOO_LONG: "好像多了幾碼",
                PhoneProblem.MALFORMED: "格式看起來不對",
            }[d["problem"]]
            return f"{at}：電話「{d['phone']}」{looks}，已先收下，請確認號碼。"
        case FindingKind.DUPLICATE_PHONE_PICKUP:
            stored = d.get("stored_order_nos") or ()
            also = f"跟之前收過的單號 {'、'.join(stored)} " if stored else ""
            return f"{at}：{also}同一支電話、同一天取貨，已先收下，請確認是不是重複登記。"
        case FindingKind.SKIPPED_SHEET:
            sheet = f.locations[0].sheet
            if d["reason"] == SkipReason.OTHER_STORE:
                return (
                    f"略過分頁：{sheet}（這個分頁的門市代碼是 {d['other_store_code']}，"
                    "跟這份檔案的其他分頁不一樣，系統沒有讀）。"
                )
            return f"略過分頁：{sheet}（這個分頁的欄位跟範本不一樣，系統沒有讀）。"
    raise AssertionError(f.kind)


def _at(f: Finding) -> str:
    """「喜餅訂單 第 5、6 列（單號 0458）」; several sheets are joined with 、."""
    where = "、".join(f"{loc.sheet} 第 {'、'.join(map(str, loc.rows))} 列" for loc in f.locations)
    return f"{where}（單號 {'、'.join(f.order_nos)}）" if f.order_nos else where


def _date(d: date) -> str:
    return f"{d.year}/{d.month:02d}/{d.day:02d}"


def _value(v: Any) -> str:
    if v is None:
        return "空白"
    if isinstance(v, date):
        return _date(v)
    return str(v)


def _quoted_number(text: str) -> str:
    """Numbers as they are (填了 0), anything else in 「」."""
    try:
        float(text)
    except ValueError:
        return f"「{text}」"
    return text
