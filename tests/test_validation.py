"""Dirty files through process_upload: per-row errors and warnings, tolerant reading,
several sheets, whole-file failures, and the LINE length limit."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime

import pytest
from sqlalchemy import select

from bakery.catalog import store_by_code
from bakery.models import Order, Upload
from bakery.pipeline import process_upload
from bakery.template import FIRST_DATA_ROW, SHEET_NAME, build_template
from bakery.xlsx import workbook_bytes

# 單號, 訂購人姓名, 電話, 接單日, 取貨日, 宴客日, 新人姓名, 接單人, 品項, 盒數, 備註, 狀態
ROW = ("0301", "王小姐", "0912-345-678", date(2026, 10, 20), date(2026, 11, 28), None,
       "陳志豪、林佳蓉", "美玲", "龍鳳喜餅", 100, None, None)


def row(**changes) -> tuple:
    names = ("order_no", "name", "phone", "received", "pickup", "banquet",
             "couple", "taken_by", "product", "qty", "note", "status")
    values = dict(zip(names, ROW, strict=True))
    values.update(changes)
    return tuple(values[n] for n in names)


def workbook_file(sheets: dict[str, Sequence[Sequence]], store_code: str = "TC01") -> bytes:
    """A 範本 file whose order sheets are named and filled as given (first sheet = template sheet)."""
    wb = build_template(store_by_code(store_code))
    template = wb[SHEET_NAME]
    filled = [template, *(wb.copy_worksheet(template) for _ in list(sheets)[1:])]
    for ws, (title, rows) in zip(filled, sheets.items(), strict=True):
        ws.title = title
        for r, values in enumerate(rows, start=FIRST_DATA_ROW):
            for c, value in enumerate(values, start=1):
                ws.cell(row=r, column=c, value=value)
    return workbook_bytes(wb, datetime(2026, 10, 21, 9, 0))


def upload(session, now, file_bytes: bytes, uploader: str = "Udemo-TC01"):
    return process_upload(
        session, uploader_line_id=uploader, filename="upload.xlsx", file_bytes=file_bytes, now=now
    )


def orders(session) -> dict[str, Order]:
    return {o.order_no: o for o in session.scalars(select(Order))}


def kinds(result) -> list[tuple[str, str]]:
    return [(f.kind.value, f.severity.value) for f in result.outcome.findings]


@pytest.mark.parametrize(
    "written, expected",
    [
        ("2026/11/28", date(2026, 11, 28)),
        ("2026-11-28", date(2026, 11, 28)),
        ("115/11/28", date(2026, 11, 28)),
        ("115年11月28日", date(2026, 11, 28)),
        ("11/28", date(2026, 11, 28)),
        ("1/5", date(2027, 1, 5)),  # month/day: the year nearest to today (2026-10-21)
        (46354, date(2026, 11, 28)),  # an Excel serial number without date formatting
        (datetime(2026, 11, 28), date(2026, 11, 28)),
    ],
)
def test_pickup_date_written_in_any_common_way_is_read(session, now, written, expected):
    upload(session, now, workbook_file({SHEET_NAME: [row(pickup=written)]}))

    assert orders(session)["0301"].pickup_on == expected


@pytest.mark.parametrize("written", ["下週六", "2026/13/01", "115/02/30"])
def test_unreadable_date_drops_the_row(session, now, written):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(pickup=written), row(order_no="0302")]}))

    assert set(orders(session)) == {"0302"}
    assert kinds(result) == [("unparseable_date", "error")]
    assert f"喜餅訂單 第 4 列（單號 0301）：取貨日寫「{written}」，系統看不懂，這一列沒有收。" in result.reply_text


def test_missing_pickup_date_drops_the_row(session, now):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(pickup=None)]}))

    assert orders(session) == {}
    assert "喜餅訂單 第 4 列（單號 0301）：沒有填取貨日，這一列沒有收。" in result.reply_text


@pytest.mark.parametrize("qty", [0, -5, 2.5, "十盒", None])
def test_quantity_must_be_a_positive_whole_number(session, now, qty):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(qty=qty)]}))

    assert orders(session) == {}
    assert kinds(result) == [("invalid_quantity", "error")]
    assert result.outcome.rejected_row_count == 1


def test_bad_row_in_a_multi_row_order_drops_only_that_row(session, now):
    result = upload(
        session, now, workbook_file({SHEET_NAME: [row(), row(product="鳳梨酥禮盒", qty=0)]})
    )

    assert [ln.product.name for ln in orders(session)["0301"].lines] == ["龍鳳喜餅"]
    assert result.reply_text.startswith("台中中正店（TC01）：收到 1 張喜餅訂單、1 筆訂單明細。有 1 列沒有收")


@pytest.mark.parametrize("written", ["龍鳳喜餅禮盒", "龍鳳 喜餅", "龍鳯喜餅", "鳳梨"])
def test_product_is_matched_only_by_name_or_alias_never_fuzzy(session, now, written):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(product=written)]}))

    assert orders(session) == {}
    assert f"品項「{written}」不在商品清單裡，這一列沒有收。" in result.reply_text


def test_one_row_with_several_problems_lists_each_and_counts_the_row_once(session, now):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(order_no=None, qty=0, product="月下")]}))

    assert {k for k, _ in kinds(result)} == {"missing_order_no", "invalid_quantity", "unknown_product"}
    assert result.outcome.rejected_row_count == 1


def test_same_product_twice_in_one_order_drops_the_order(session, now):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(), row(product="龍鳳餅", qty=20)]}))

    assert orders(session) == {}
    assert kinds(result) == [("duplicate_product", "error")]
    assert "喜餅訂單 第 4、5 列（單號 0301）：同一張單的龍鳳喜餅寫了好幾列，整張單沒有收。" in result.reply_text


def test_order_fields_differing_between_rows_drop_the_whole_order(session, now):
    result = upload(
        session, now,
        workbook_file({SHEET_NAME: [row(), row(product="鳳梨酥禮盒", phone="0933-000-111"), row(order_no="0302")]}),
    )

    assert set(orders(session)) == {"0302"}
    assert (
        "喜餅訂單 第 4、5 列（單號 0301）：同一張單的電話不一樣（0912-345-678、0933-000-111），整張單沒有收。"
        in result.reply_text
    )


def test_phone_written_with_other_separators_is_the_same_phone(session, now):
    upload(session, now, workbook_file({SHEET_NAME: [row(), row(product="鳳梨酥禮盒", phone="0912 345 678")]}))

    assert len(orders(session)["0301"].lines) == 2


def test_every_order_sheet_is_read_and_other_sheets_are_listed_as_skipped(session, now):
    wb = build_template(store_by_code("TC01"))
    ws = wb[SHEET_NAME]
    ws.title = "十月"
    for c, v in enumerate(row(), start=1):
        ws.cell(row=FIRST_DATA_ROW, column=c, value=v)
    nov = wb.copy_worksheet(ws)
    nov.title = "十一月"
    nov.cell(row=FIRST_DATA_ROW, column=1, value="0302")
    nov.cell(row=FIRST_DATA_ROW, column=3, value="0933-000-111")
    wb.create_sheet("備忘")["A1"] = "提袋快用完了"
    wb.create_sheet("空白")

    result = upload(session, now, workbook_bytes(wb, datetime(2026, 10, 21, 9, 0)))

    assert set(orders(session)) == {"0301", "0302"}
    assert kinds(result) == [("skipped_sheet", "info")]
    assert "略過分頁：備忘（這個分頁的欄位跟範本不一樣，系統沒有讀）。" in result.reply_text


def test_one_order_split_over_sheets_is_kept_when_consistent(session, now):
    upload(session, now, workbook_file({"十月": [row()], "十一月": [row(product="鳳梨酥禮盒")]}))

    assert len(orders(session)["0301"].lines) == 2


def test_one_order_disagreeing_across_sheets_is_dropped_whole(session, now):
    result = upload(
        session, now,
        workbook_file({"十月": [row(), row(order_no="0302")],
                       "十一月": [row(product="鳳梨酥禮盒", pickup=date(2026, 12, 5))]}),
    )

    assert set(orders(session)) == {"0302"}
    assert (
        "十月 第 4 列、十一月 第 4 列（單號 0301）：同一張單的取貨日不一樣（2026/11/28、2026/12/05），整張單沒有收。"
        in result.reply_text
    )
    assert [(s.sheet, s.rows) for s in result.outcome.rejected_rows] == [("十月", (4,)), ("十一月", (4,))]


def test_sheet_of_another_store_is_skipped(session, now):
    wb = build_template(store_by_code("TC01"))
    ws = wb[SHEET_NAME]
    for c, v in enumerate(row(), start=1):
        ws.cell(row=FIRST_DATA_ROW, column=c, value=v)
    other = wb.copy_worksheet(ws)
    other.title = "彰化"
    other["B1"] = "CH01"

    result = upload(session, now, workbook_bytes(wb, datetime(2026, 10, 21, 9, 0)))

    assert set(orders(session)) == {"0301"}
    assert "略過分頁：彰化（這個分頁的門市代碼是 CH01" in result.reply_text


def test_reordered_synonym_and_extra_columns_are_read(session, now):
    headers = ["品名", "數量", "訂單編號", "客人備註", "手機", "訂購人", "接單日期", "取貨日期",
               "宴客日", "新人", "承辦人", "附註", "狀態"]
    wb = build_template(store_by_code("TC01"), headers)
    values = ["鳳梨酥", 80, "0301", "很急", "0912345678", "王小姐", "115/10/20", "115/11/28",
              None, "陳志豪、林佳蓉", "美玲", "要提袋", None]
    for c, v in enumerate(values, start=1):
        wb[SHEET_NAME].cell(row=FIRST_DATA_ROW, column=c, value=v)

    result = upload(session, now, workbook_bytes(wb, datetime(2026, 10, 21, 9, 0)))

    o = orders(session)["0301"]
    assert (o.orderer_name, o.phone, o.pickup_on, o.taken_by) == ("王小姐", "0912345678", date(2026, 11, 28), "美玲")
    assert [(ln.product.name, ln.quantity, ln.note) for ln in o.lines] == [("鳳梨酥禮盒", 80, "要提袋")]
    assert result.outcome.findings == ()


@pytest.mark.parametrize(
    "pickup, expected",
    [
        (date(2026, 10, 21), "取貨日 2026/10/21 就是今天，已先收下，請確認中央廚房來得及做。"),
        (date(2026, 10, 24), "取貨日 2026/10/24 只剩 3 天，已先收下，請確認中央廚房來得及做。"),
        (date(2026, 10, 20), "取貨日 2026/10/20 已經過了，已先收下，請確認日期有沒有打錯。"),
    ],
)
def test_pickup_soon_or_past_is_kept_with_a_warning(session, now, pickup, expected):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(pickup=pickup)]}))

    assert set(orders(session)) == {"0301"}
    assert f"喜餅訂單 第 4 列（單號 0301）：{expected}" in result.reply_text


def test_pickup_four_days_out_is_not_too_soon(session, now):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(pickup=date(2026, 10, 25))]}))

    assert result.outcome.findings == ()


@pytest.mark.parametrize(
    "phone, flagged",
    [("0912-345-678", False), ("+886 912 345 678", False), ("04-2345-6789", False),
     ("049-547-4284", False), ("0912-3456", True), ("0912-345-6789", True), ("09123x5678", True)],
)
def test_odd_phone_is_kept_with_a_warning(session, now, phone, flagged):
    result = upload(session, now, workbook_file({SHEET_NAME: [row(phone=phone)]}))

    assert set(orders(session)) == {"0301"}
    assert (("phone_format", "warning") in kinds(result)) is flagged


def test_quantity_over_300_is_kept_with_a_warning_but_300_is_not(session, now):
    result = upload(
        session, now,
        workbook_file({SHEET_NAME: [row(qty=300), row(order_no="0302", phone="0933-000-111", qty=301)]}),
    )

    assert set(orders(session)) == {"0301", "0302"}
    assert kinds(result) == [("quantity_over_threshold", "warning")]
    assert "喜餅訂單 第 5 列（單號 0302）：龍鳳喜餅 301 盒比平常多很多" in result.reply_text


def test_same_phone_and_pickup_as_an_order_received_earlier_is_flagged(session, now):
    upload(session, now, workbook_file({SHEET_NAME: [row()]}))

    result = upload(session, now, workbook_file({SHEET_NAME: [row(order_no="0350", phone="0912345678")]}))

    assert set(orders(session)) == {"0301", "0350"}
    assert (
        "喜餅訂單 第 4 列（單號 0350）：跟之前收過的單號 0301 同一支電話、同一天取貨，已先收下，請確認是不是重複登記。"
        in result.reply_text
    )


def test_reuploading_the_same_order_is_not_a_duplicate(session, now):
    upload(session, now, workbook_file({SHEET_NAME: [row()]}))

    result = upload(session, now, workbook_file({SHEET_NAME: [row()]}))

    assert result.outcome.findings == ()


def test_errors_and_warnings_are_listed_in_separate_sections(session, now):
    result = upload(
        session, now,
        workbook_file({SHEET_NAME: [row(qty=0), row(order_no="0302", qty=400)]}),
    )

    text = result.reply_text
    errors, warnings = text.index("【沒有收，請改好後再傳一次】"), text.index("【已先收下，請再確認】")
    assert errors < text.index("單號 0301") < warnings < text.index("單號 0302")


@pytest.mark.parametrize(
    "file_bytes, reason",
    [
        (b"not an excel file", "系統打不開這份檔案"),
        (b"", "系統打不開這份檔案"),
    ],
)
def test_unreadable_file_is_kept_and_answered(session, now, file_bytes, reason):
    result = upload(session, now, file_bytes)

    assert result.reply_text.startswith(f"這份檔案沒有收：{reason}")
    stored = session.get(Upload, result.upload_id)
    assert (stored.content, stored.reply_text, stored.store_code) == (file_bytes, result.reply_text, None)


def test_unknown_store_code_is_answered(session, now):
    wb = build_template(store_by_code("TC01"))
    wb[SHEET_NAME]["B1"] = "XX99"
    for c, v in enumerate(row(), start=1):
        wb[SHEET_NAME].cell(row=FIRST_DATA_ROW, column=c, value=v)

    result = upload(session, now, workbook_bytes(wb, datetime(2026, 10, 21, 9, 0)))

    assert result.reply_text.startswith("這份檔案沒有收：門市代碼「XX99」不在門市清單裡。")
    assert orders(session) == {}


def test_missing_store_code_is_answered(session, now):
    wb = build_template(store_by_code("TC01"))
    wb[SHEET_NAME]["B1"] = None

    result = upload(session, now, workbook_bytes(wb, datetime(2026, 10, 21, 9, 0)))

    assert result.reply_text.startswith("這份檔案沒有收：範本左上角的門市代碼是空的。")


def test_workbook_without_an_order_sheet_is_answered(session, now):
    wb = build_template(store_by_code("TC01"))
    wb[SHEET_NAME].delete_rows(3)  # no header row any more

    result = upload(session, now, workbook_bytes(wb, datetime(2026, 10, 21, 9, 0)))

    assert result.reply_text.startswith("這份檔案沒有收：檔案裡找不到喜餅訂單的欄位")


def test_long_reply_is_cut_to_the_line_limit_with_a_link_to_the_rest(session, now, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://bakery.example/")
    rows = [row(order_no=f"9{i:03d}", product=f"不存在的品項{i}") for i in range(400)]

    result = upload(session, now, workbook_file({SHEET_NAME: rows}))

    text = result.reply_text
    assert len(text) <= 5000
    assert text.startswith("台中中正店（TC01）：收到 0 張喜餅訂單、0 筆訂單明細。有 400 列沒有收")
    m = re.search(r"\n\n其餘 (\d+) 項請看網頁：(\S+)\n\n廚房彙總：https://bakery.example/kitchen$", text)
    assert m[2] == f"https://bakery.example/uploads/{result.upload_id}"
    listed = text.count("不在商品清單裡")
    assert listed > 0 and listed + int(m[1]) == 400
    assert result.report_text.count("不在商品清單裡") == 400
    assert session.get(Upload, result.upload_id).report_text == result.report_text
