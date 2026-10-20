"""歷史資料匯入: converted legacy files imported by a 總部人員 as 歷史資料."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from bakery.legacy import convert
from bakery.models import Change, Order, OrderLine, StoreBinding, Upload
from bakery.pipeline import process_upload

MOCK = Path(__file__).resolve().parents[1] / "mock_data"
MANIFEST = json.loads((MOCK / "expectations.json").read_text())
LEGACY = {lg["store_code"]: lg for lg in MANIFEST["legacy"]}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _converted(store_code: str) -> bytes:
    return convert(store_code, (MOCK / LEGACY[store_code]["file"]).read_bytes()).content


def _import(client, *store_codes: str, content: bytes | None = None):
    files = [
        ("files", (f"{code}_歷史資料.xlsx", content or _converted(code), XLSX)) for code in store_codes
    ]
    return client.post("/history/import", files=files)


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_import_takes_in_both_converted_files_as_historical_orders(client, session, now):
    resp = _import(client, "TC02", "CH01")

    assert resp.status_code == 200
    assert "台中北屯店（TC02）：收到 7 張喜餅訂單、11 筆訂單明細。" in resp.text
    assert "彰化中華店（CH01）：收到 6 張喜餅訂單、10 筆訂單明細。" in resp.text
    orders = session.scalars(select(Order)).all()
    assert len(orders) == 13 and _count(session, OrderLine) == 21
    assert all(o.is_historical for o in orders)
    # What lets the 廚房彙總 leave them out: flagged, and every 取貨日 already past.
    assert all(o.pickup_on < now.date() for o in orders)


def test_import_skips_the_past_pickup_warnings_and_replies_to_nobody(client, session):
    bindings = _count(session, StoreBinding)

    resp = _import(client, "TC02")

    assert "已經過了" not in resp.text
    upload = session.scalars(select(Upload)).one()
    assert upload.is_historical and upload.reply_text is None
    assert upload.uploader_id is None
    assert _count(session, StoreBinding) == bindings  # no 傳檔者, so no 門市綁定


def test_import_keeps_the_original_and_shows_who_imported_it(client, session):
    _import(client, "CH01")

    upload = session.scalars(select(Upload)).one()
    assert client.get(f"/uploads/{upload.id}/original").content == _converted("CH01")
    rows = re.findall(r'<td class="submitted-by">([^<]*)</td>', client.get("/uploads").text)
    assert rows == ["歷史資料匯入：林雅文（總部）"]


def test_imported_orders_are_new_orders_in_the_change_log(client, session):
    _import(client, "TC02")

    changes = session.scalars(select(Change)).all()
    assert len(changes) == 7 and all(c.is_new_order for c in changes)


def test_reimporting_the_same_file_adds_no_orders(client, session):
    _import(client, "TC02")
    resp = _import(client, "TC02")

    assert "這份檔案的內容之前都收過了，沒有新單，也沒有修改。" in resp.text
    assert _count(session, Order) == 7
    assert _count(session, OrderLine) == 11
    assert _count(session, Upload) == 2  # both originals kept


def test_reconverting_and_reimporting_adds_no_orders(client, session):
    _import(client, "CH01", "CH01")  # each file converted afresh: same bytes, same 單號

    assert _count(session, Order) == 6
    assert _count(session, OrderLine) == 10


def test_a_corrected_reimport_is_applied_without_waiting_for_hq(client, session, make_template_file):
    # 單號, 訂購人姓名, 電話, 接單日, 取貨日, 宴客日, 新人姓名, 接單人, 品項, 盒數, 備註, 狀態
    first = ("H-20260601-01", "王小姐", "0912-345-678", date(2026, 6, 1), date(2026, 6, 20), None,
             None, None, "龍鳳喜餅", 50, None, None)
    corrected = ("H-20260601-01", "王小姐", "0933-222-111", date(2026, 6, 1), date(2026, 6, 27), None,
                 None, None, "龍鳳喜餅", 80, None, None)
    _import(client, "TC02", content=make_template_file("TC02", [first]))

    _import(client, "TC02", content=make_template_file("TC02", [corrected]))

    order = session.scalars(select(Order)).one()
    session.refresh(order)
    assert (order.phone, order.pickup_on, order.lines[0].quantity) == ("0933-222-111", date(2026, 6, 27), 80)


def test_import_never_overwrites_an_order_sent_after_go_live(client, session, now, make_template_file):
    live = ("0301", "陳先生", "0911-111-111", date(2026, 10, 20), date(2026, 11, 28), None,
            None, None, "龍鳳喜餅", 120, None, None)
    process_upload(
        session, uploader_line_id="Udemo-TC01", filename="TC01.xlsx",
        file_bytes=make_template_file("TC01", [live]), now=now,
    )
    old = ("0301", "林小姐", "0922-222-222", date(2026, 3, 1), date(2026, 3, 20), None,
           None, None, "鳳梨酥禮盒", 30, None, None)
    other = ("0150", "林小姐", "0922-222-222", date(2026, 3, 1), date(2026, 3, 21), None,
             None, None, "鳳梨酥禮盒", 40, None, None)

    resp = _import(client, "TC01", content=make_template_file("TC01", [old, other]))

    assert (
        "喜餅訂單 第 4 列（單號 0301）：這個單號已經有上線後收到的喜餅訂單，歷史資料不會蓋過它，整張單沒有匯入。"
        in resp.text
    )
    orders = {o.order_no: o for o in session.scalars(select(Order))}
    session.refresh(orders["0301"])
    assert not orders["0301"].is_historical and orders["0301"].orderer_name == "陳先生"
    assert orders["0150"].is_historical


def test_a_line_upload_cannot_be_historical(session, now):
    with pytest.raises(ValueError):
        process_upload(
            session, uploader_line_id="Udemo-TC01", filename="x.xlsx", file_bytes=b"",
            now=now, historical=True,
        )


def test_owner_cannot_import(make_client, session):
    resp = _import(make_client("owner"), "TC02")

    assert resp.status_code == 403
    assert _count(session, Upload) == 0


def test_nav_offers_the_import_page_to_hq_only(make_client):
    def nav(username: str) -> str:
        return re.search(r"<nav>(.*?)</nav>", make_client(username).get("/orders").text, re.S)[1]

    assert 'href="/history/import"' in nav("hq-lin")
    assert 'href="/history/import"' not in nav("owner")
    assert 'href="/history/import"' not in nav("kitchen")


# ---------------------------------------------------------------- 客人資料

LEGACY_RETURNING = [
    rc for rc in MANIFEST["returning_customers"]
    if any(a["file"].startswith("legacy/") for a in rc["appearances"])
]


def _customer_links(html: str) -> dict[str, str]:
    return {
        phone: link
        for link, phone in re.findall(r'<tr class="customer">.*?<a href="([^"]+)">([^<]+)</a>', html, re.S)
    }


@pytest.mark.parametrize("returning", LEGACY_RETURNING, ids=[rc["phone_digits"] for rc in LEGACY_RETURNING])
def test_returning_customers_only_visible_after_import_appear_in_customer_records(
    client, session, now, returning
):
    assert LEGACY_RETURNING, "the 對照表 lists 回頭客 found through 歷史資料"
    for f in (f for f in MANIFEST["files"] if f["stage"] == "day1"):
        path = MOCK / f["file"]
        process_upload(
            session, uploader_line_id=f"Udemo-{f['store_code']}", filename=path.name,
            file_bytes=path.read_bytes(), now=now,
        )
    phone = returning["phone_digits"]
    before = client.get(_customer_links(client.get("/customers").text)[phone]).text
    assert len(re.findall(r'<td class="order-no">', before)) == 1

    _import(client, *sorted(LEGACY))

    html = client.get(_customer_links(client.get("/customers").text)[phone]).text
    order_nos = re.findall(r'<td class="order-no"><a href="/orders/\d+">([^<]+)</a>', html)
    day1 = [a["ref"].removeprefix("單號 ") for a in returning["appearances"] if a["file"].startswith("day1/")]
    assert len(order_nos) == 2
    assert set(day1) < set(order_nos)
    assert any(no.startswith("H-") for no in order_nos)
    for a in returning["appearances"]:
        assert a["orderer_name"] in html
    assert "歷史資料" in html
    assert "同一支電話留過不同的姓名" in html
