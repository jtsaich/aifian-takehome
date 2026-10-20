"""The one place that turns an UploadOutcome into the 繁中 reply the 傳檔者 reads.

The same text goes to the LINE group and to the 模擬群組上傳 page. Every
problem names its place (分頁 + Excel 列號) and says, in store language, what
to do; errors (not accepted) and warnings (accepted) are listed apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from bakery.outcome import (
    Failure,
    FailureKind,
    Finding,
    FindingKind,
    Severity,
    SkipReason,
    UploadOutcome,
)
from bakery.phone import PhoneProblem

# LINE text messages hold at most 5,000 characters.
LINE_TEXT_LIMIT = 5000
# Shown in errors about dates, as the format to follow.
DATE_EXAMPLE = "2026/11/08"

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
    items = [
        (title, f"・{finding_text(f)}")
        for severity, title in _SECTIONS
        for f in outcome.findings
        if f.severity == severity
    ]
    report = _join(head, items)
    if len(report) <= LINE_TEXT_LIMIT:
        return Reply(report, report)

    kept = 0
    for k in range(1, len(items) + 1):
        if len(_join(head, items[:k]) + _rest(len(items) - k, report_url)) > LINE_TEXT_LIMIT:
            break
        kept = k
    return Reply(_join(head, items[:kept]) + _rest(len(items) - kept, report_url), report)


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
    if outcome.failure is not None:
        return f"這份檔案沒有收：{failure_text(outcome.failure)}"
    text = (
        f"{outcome.store_name}（{outcome.store_code}）："
        f"收到 {outcome.order_count} 張喜餅訂單、{outcome.line_count} 筆訂單明細。"
    )
    if outcome.rejected_row_count:
        text += f"有 {outcome.rejected_row_count} 列沒有收，請改好後再傳一次。"
    warnings = sum(1 for f in outcome.findings if f.severity == Severity.WARNING)
    if warnings:
        text += f"有 {warnings} 個地方已先收下，請再確認。"
    return text


def failure_text(failure: Failure) -> str:
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
        case FailureKind.INTERNAL_ERROR:
            return "系統處理時出了問題，檔案已經保存，請通知總部處理，不用重傳。"
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
