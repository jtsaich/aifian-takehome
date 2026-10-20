"""修改截止點, 待確認 and 品項 upkeep (ticket 07).

A production-affecting 修改 past the cutoff, and every suspected reused 單號, waits
on the 待處理 page for a 總部人員. Confirming applies it, 退回 keeps the old content;
the 門市 hears the outcome at the top of its next reply. Sending the held content
again only brings a reminder.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from bakery.models import Change, LineStatus, Order, PendingReview
from bakery.pipeline import process_upload

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Day 1 is 2026-10-21 (conftest NOW); 取貨日 10/27 is 6 days out on day 1, 5 on day 2:
# past the default 7-day cutoff, but not close enough for the 取貨日 warning.
NEAR = date(2026, 10, 27)
FAR = date(2026, 11, 28)

ORDER = {
    "order_no": "0301",
    "orderer_name": "王小姐",
    "phone": "0912-345-678",
    "received_on": date(2026, 10, 1),
    "pickup_on": NEAR,
    "banquet_on": None,
    "couple_names": "陳志豪、林佳蓉",
    "taken_by": "美玲",
}


def row(product: str, quantity: int, *, note=None, status=None, **order) -> tuple:
    o = {**ORDER, **order}
    return (
        o["order_no"], o["orderer_name"], o["phone"], o["received_on"], o["pickup_on"],
        o["banquet_on"], o["couple_names"], o["taken_by"], product, quantity, note, status,
    )


# Every reply ends with the 廚房彙總 link.
KITCHEN = "\n\n廚房彙總：/kitchen"
UNCHANGED = f"台中中正店（TC01）：這份檔案的內容之前都收過了，沒有新單，也沒有修改。{KITCHEN}"
HELD_SUMMARY = "台中中正店（TC01）：修改 1 張，其中 1 張待總部確認。"


@pytest.fixture
def send(session, now, make_template_file):
    """Send rows as a TC01 file `day` days after day 1; returns the reply text."""

    def send(rows, *, day: int = 0) -> str:
        return process_upload(
            session,
            uploader_line_id="Udemo-TC01",
            filename=f"TC01_day{day + 1}.xlsx",
            file_bytes=make_template_file("TC01", rows),
            now=now + timedelta(days=day),
        ).reply_text

    return send


def _order(session, order_no="0301") -> Order:
    order = session.scalar(select(Order).where(Order.order_no == order_no))
    session.refresh(order)
    return order


def _boxes(session, order_no="0301") -> dict[str, tuple[int, LineStatus]]:
    return {ln.product.name: (ln.quantity, ln.status) for ln in _order(session, order_no).lines}


def _reviews(session) -> list[tuple[str, str]]:
    session.expire_all()
    return [(r.change.order.order_no, r.status) for r in session.scalars(select(PendingReview).order_by(PendingReview.id))]


def _decide(client, decision: str, review_id: int = 1):
    return client.post("/reviews", data={"review_id": review_id, "decision": decision}, follow_redirects=False)


# --- 修改截止點 --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days_left", "held"),
    [pytest.param(8, False, id="N+1 天前"), pytest.param(7, False, id="剛好第 N 天"), pytest.param(6, True, id="N-1 天前")],
)
def test_cutoff_is_the_nth_day_before_pickup_and_that_day_still_applies(session, send, now, days_left, held):
    pickup = now.date() + timedelta(days=days_left + 1)
    send([row("龍鳳喜餅", 80, pickup_on=pickup)])

    reply = send([row("龍鳳喜餅", 120, pickup_on=pickup)], day=1)  # `days_left` days before 取貨日

    if held:
        assert reply.startswith(HELD_SUMMARY)
        assert "・單號 0301：追加，龍鳳喜餅 80→120 盒（已過截止點，待總部確認）" in reply
        assert _boxes(session) == {"龍鳳喜餅": (80, LineStatus.ACTIVE)}
    else:
        assert reply.startswith("台中中正店（TC01）：修改 1 張。")
        assert "・單號 0301：追加，龍鳳喜餅 80→120 盒\n" in f"{reply}\n"
        assert _boxes(session) == {"龍鳳喜餅": (120, LineStatus.ACTIVE)}


@pytest.mark.parametrize(
    ("day2", "line"),
    [
        pytest.param([row("龍鳳喜餅", 60)], "單號 0301：減量，龍鳳喜餅 80→60 盒", id="減量"),
        pytest.param([row("龍鳳喜餅", 80, status="取消")], "單號 0301：取消，龍鳳喜餅 80 盒不再生產", id="取消"),
        pytest.param(
            [row("龍鳳喜餅", 80, pickup_on=FAR)], "單號 0301：改取貨日，2026/10/27→2026/11/28", id="延後取貨日"
        ),
        pytest.param(
            [row("龍鳳喜餅", 100, couple_names="王大明、李小華")],
            "單號 0301：追加＋資料更正，龍鳳喜餅 80→100 盒；新人姓名 陳志豪、林佳蓉→王大明、李小華",
            id="追加＋資料更正整筆等",
        ),
    ],
)
def test_every_production_change_past_the_cutoff_waits(session, send, day2, line):
    send([row("龍鳳喜餅", 80)])

    reply = send(day2, day=1)

    assert reply.startswith(HELD_SUMMARY)
    assert f"・{line}（已過截止點，待總部確認）" in reply
    order = _order(session)
    assert (order.pickup_on, order.couple_names) == (NEAR, "陳志豪、林佳蓉")
    assert _boxes(session) == {"龍鳳喜餅": (80, LineStatus.ACTIVE)}
    assert _reviews(session) == [("0301", "pending")]


def test_pulling_a_far_pickup_into_the_cutoff_waits(session, send):
    send([row("龍鳳喜餅", 80, pickup_on=FAR)])

    reply = send([row("龍鳳喜餅", 80, pickup_on=NEAR)], day=1)

    assert "・單號 0301：改取貨日，2026/11/28→2026/10/27（已過截止點，待總部確認）" in reply
    assert _order(session).pickup_on == FAR


def test_info_fix_past_the_cutoff_applies_directly(session, send):
    send([row("龍鳳喜餅", 80)])

    reply = send([row("龍鳳喜餅", 80, couple_names="王大明、李小華", phone="0933-222-111")], day=1)

    assert reply.startswith("台中中正店（TC01）：修改 1 張。")
    assert _order(session).couple_names == "王大明、李小華"
    assert _reviews(session) == []


def test_suspected_reuse_waits_even_far_from_the_cutoff(session, send):
    send([row("龍鳳喜餅", 80, pickup_on=FAR)])

    reply = send([row("龍鳳喜餅", 200, pickup_on=FAR, phone="0940-720-754")], day=1)

    assert reply.startswith(HELD_SUMMARY)
    assert "可能是兩張不同的單用了同一個單號" in reply
    assert "已過截止點" not in reply
    assert _reviews(session) == [("0301", "pending")]


def test_historical_import_never_waits(session, now, make_template_file):
    past = date(2025, 12, 6)

    def import_rows(rows):
        return process_upload(
            session, uploader_line_id=None, filename="舊資料.xlsx", now=now, historical=True,
            file_bytes=make_template_file("TC01", rows),
        )

    import_rows([row("龍鳳喜餅", 80, pickup_on=past, received_on=date(2025, 11, 1))])
    result = import_rows([row("龍鳳喜餅", 120, pickup_on=past, received_on=date(2025, 11, 1))])

    assert [c.decision for c in result.outcome.changes] == ["applied"]
    assert _boxes(session) == {"龍鳳喜餅": (120, LineStatus.ACTIVE)}
    assert _reviews(session) == []


def test_hq_sets_the_cutoff_days_on_the_web(session, send, client, make_client):
    assert re.search(r'class="cutoff-days">7<', client.get("/settings").text)

    resp = client.post("/settings", data={"cutoff": "4"}, follow_redirects=False)

    assert resp.status_code == 303
    assert re.search(r'class="cutoff-days">4<', make_client("owner").get("/settings").text)
    send([row("龍鳳喜餅", 80)])
    # 取貨日 10/27 is 5 days after day 2: within 7, but not within 4.
    assert send([row("龍鳳喜餅", 120)], day=1).startswith("台中中正店（TC01）：修改 1 張。")


@pytest.mark.parametrize("value", ["-1", "abc", "61", ""])
def test_cutoff_days_must_be_a_sensible_whole_number(client, value):
    resp = client.post("/settings", data={"cutoff": value})

    assert resp.status_code == 422
    assert re.search(r'class="cutoff-days">7<', client.get("/settings").text)


# --- 待處理 page: confirm / 退回 -----------------------------------------------------


@pytest.fixture
def held(send):
    """0301 on record with 龍鳳喜餅 80; day 2 asks for 120, past the cutoff."""
    send([row("龍鳳喜餅", 80)])
    send([row("龍鳳喜餅", 120)], day=1)


def test_pending_page_shows_kind_values_store_and_upload(held, client):
    html = client.get("/reviews").text

    [pending] = re.findall(r'<tr class="review pending".*?</tr>', html, re.S)
    assert "台中中正店（TC01）" in pending
    assert ">0301</a>" in pending
    assert "追加" in pending and "已過修改截止點" in pending
    assert "盒數（龍鳳喜餅）：80 → 120" in pending
    assert 'href="/uploads/2">上傳 #2</a>' in pending
    assert 'value="confirm"' in pending and 'value="reject"' in pending


def test_owner_sees_the_pending_page_but_cannot_decide(held, make_client, session):
    owner = make_client("owner")

    html = owner.get("/reviews").text
    assert "盒數（龍鳳喜餅）：80 → 120" in html
    assert 'value="confirm"' not in html
    assert _decide(owner, "confirm").status_code == 403
    assert make_client("kitchen").get("/reviews").status_code == 403
    assert _decide(make_client("kitchen"), "reject").status_code == 403
    assert _reviews(session) == [("0301", "pending")]


def test_confirm_applies_the_change_and_records_who(held, session, make_client, now):
    resp = _decide(make_client("hq-chen"), "confirm")

    assert resp.status_code == 303
    assert _boxes(session) == {"龍鳳喜餅": (120, LineStatus.ACTIVE)}
    review = session.scalar(select(PendingReview))
    assert (review.status, review.decided_by.username, review.decided_at) == ("confirmed", "hq-chen", now)
    decided = make_client("owner").get("/reviews").text
    assert "已確認（陳志明（總部）" in decided
    audit = make_client("owner").get(f"/orders/{_order(session).id}").text
    assert "總部已確認並套用：陳志明（總部）" in audit


def test_reject_keeps_the_old_content(held, session, client):
    assert _decide(client, "reject").status_code == 303

    assert _boxes(session) == {"龍鳳喜餅": (80, LineStatus.ACTIVE)}
    review = session.scalar(select(PendingReview))
    assert (review.status, review.decided_by.username) == ("rejected", "hq-lin")
    assert "總部已退回，未套用：林雅文（總部）" in client.get(f"/orders/{_order(session).id}").text


def test_a_decided_review_cannot_be_decided_again(held, client, make_client, session):
    _decide(client, "reject")

    assert _decide(make_client("hq-chen"), "confirm").status_code == 409
    assert _boxes(session) == {"龍鳳喜餅": (80, LineStatus.ACTIVE)}
    assert _decide(client, "confirm", review_id=99).status_code == 404


# --- what the 門市 hears afterwards ---------------------------------------------------

DECISIONS_TITLE = "【總部已處理您之前的待確認】"


def test_resending_a_pending_change_reminds_without_a_new_review(held, send, session):
    reply = send([row("龍鳳喜餅", 120)], day=2)

    assert reply == (
        "台中中正店（TC01）：1 張修改仍待總部確認。\n\n"
        "【之前傳過的修改】\n・單號 0301 龍鳳喜餅 盒數 120 仍待總部確認"
        f"{KITCHEN}"
    )
    assert _reviews(session) == [("0301", "pending")]
    assert len(session.scalars(select(Change)).all()) == 2  # 新單 + the held 修改


def test_after_reject_the_reply_tells_and_a_resend_is_reminded_until_reverted(held, send, client, session):
    _decide(client, "reject")

    reply = send([row("龍鳳喜餅", 120)], day=2)

    assert reply == (
        f"{DECISIONS_TITLE}\n"
        "・單號 0301 龍鳳喜餅 盒數 120：總部已退回，系統仍以 80 盒計算，請把 Excel 改回 80。\n\n"
        "台中中正店（TC01）：1 張修改已被總部退回。\n\n"
        "【之前傳過的修改】\n"
        "・單號 0301 龍鳳喜餅 盒數 120 已被總部退回，系統仍以 80 盒計算，請把 Excel 改回 80"
        f"{KITCHEN}"
    )
    assert _reviews(session) == [("0301", "rejected")]
    # Told once; the reminder stays while the Excel still says 120.
    again = send([row("龍鳳喜餅", 120)], day=3)
    assert DECISIONS_TITLE not in again
    assert "已被總部退回，系統仍以 80 盒計算，請把 Excel 改回 80" in again
    assert _reviews(session) == [("0301", "rejected")]

    # Back to 80: nothing more to say.
    assert send([row("龍鳳喜餅", 80)], day=4) == UNCHANGED
    assert _boxes(session) == {"龍鳳喜餅": (80, LineStatus.ACTIVE)}


def test_after_confirm_the_reply_tells_once_and_a_resend_is_unchanged(held, send, client, session):
    _decide(client, "confirm")

    reply = send([row("龍鳳喜餅", 120)], day=2)

    assert reply == (
        f"{DECISIONS_TITLE}\n"
        "・單號 0301 龍鳳喜餅 盒數 120：總部已確認，已照新的內容計算。\n\n"
        f"{UNCHANGED}"
    )
    assert send([row("龍鳳喜餅", 120)], day=3) == UNCHANGED
    assert _reviews(session) == [("0301", "confirmed")]
    assert len(session.scalars(select(Change)).all()) == 2


def test_decisions_go_to_that_stores_next_upload_only(held, client, session, now, make_template_file):
    _decide(client, "confirm")
    other = process_upload(
        session,
        uploader_line_id="Udemo-CH01",
        filename="CH01.xlsx",
        file_bytes=make_template_file("CH01", [row("咖哩大餅", 30, order_no="CH-1", pickup_on=FAR)]),
        now=now + timedelta(days=2),
    )
    assert DECISIONS_TITLE not in other.reply_text

    resp = client.post(
        "/demo/upload",
        data={"uploader_line_id": "Udemo-TC01"},
        files={"file": ("TC01.xlsx", make_template_file("TC01", [row("鳳梨酥禮盒", 20, order_no="0302")]), XLSX)},
    )
    assert f"{DECISIONS_TITLE}\n・單號 0301 龍鳳喜餅 盒數 120：總部已確認" in resp.text
    assert "上傳 #4 的回覆" in client.get("/reviews").text


def test_a_rejected_reuse_explains_what_to_do(send, client):
    send([row("龍鳳喜餅", 80, pickup_on=FAR)])
    send([row("龍鳳喜餅", 200, pickup_on=FAR, phone="0940-720-754")], day=1)
    _decide(client, "reject")

    reply = send([row("龍鳳喜餅", 200, pickup_on=FAR, phone="0940-720-754")], day=2)

    assert reply.startswith(
        f"{DECISIONS_TITLE}\n・單號 0301：電話不同的那份內容已被總部退回，這個單號仍是原本那張單。"
    )
    assert "【之前傳過的修改】\n・單號 0301：電話不同的這份內容已被總部退回" in reply


def test_rejected_pickup_and_new_product_say_what_to_write_back(send, client):
    send([row("龍鳳喜餅", 80)])
    send([row("龍鳳喜餅", 80, pickup_on=FAR), row("綠豆椪禮盒", 30, pickup_on=FAR)], day=1)
    _decide(client, "reject")

    reply = send([row("龍鳳喜餅", 80, pickup_on=FAR), row("綠豆椪禮盒", 30, pickup_on=FAR)], day=2)

    assert (
        "・單號 0301 取貨日 2026/11/28、新增綠豆椪禮盒 30 盒 已被總部退回，"
        "系統仍以 取貨日 2026/10/27、沒有綠豆椪禮盒計算，請把 Excel 改回 2026/10/27、沒有綠豆椪禮盒"
    ) in reply


def test_other_content_supersedes_a_pending_change(held, send, session, client):
    reply = send([row("龍鳳喜餅", 150)], day=2)

    assert "・單號 0301：追加，龍鳳喜餅 80→150 盒（已過截止點，待總部確認）" in reply
    assert _reviews(session) == [("0301", "superseded"), ("0301", "pending")]
    html = client.get("/reviews").text
    assert html.count('<tr class="review pending"') == 1
    assert "80 → 150" in html


def test_sending_the_order_back_as_on_record_withdraws_a_pending_change(held, send, session):
    assert send([row("龍鳳喜餅", 80)], day=2) == UNCHANGED

    assert _reviews(session) == [("0301", "superseded")]
    # Asking again is a new 待確認, not a reminder.
    assert send([row("龍鳳喜餅", 120)], day=3).startswith(HELD_SUMMARY)
    assert _reviews(session) == [("0301", "superseded"), ("0301", "pending")]


# --- 品項 and 品項別名 ------------------------------------------------------------------


def _post_file(client, rows, make_template_file):
    return client.post(
        "/demo/upload",
        data={"uploader_line_id": "Udemo-TC01"},
        files={"file": ("TC01.xlsx", make_template_file("TC01", rows), XLSX)},
    ).text


def test_an_added_alias_lets_the_refused_row_in_on_resend(client, make_template_file, session):
    rows = [row("鳳梨酥", 40, pickup_on=FAR), row("金沙酥", 20, pickup_on=FAR)]
    first = _post_file(client, rows, make_template_file)
    assert "品項「金沙酥」不在商品清單裡" in first

    resp = client.post("/products", data={"kind": "alias", "product_code": "P07", "name": " 金沙酥 "}, follow_redirects=False)
    assert resp.status_code == 303
    assert re.search(r'<td class="aliases">金沙酥</td>', client.get("/products").text)

    second = _post_file(client, rows, make_template_file)
    assert "金沙酥" not in second
    assert "新增蛋黃酥禮盒 20 盒" in second
    assert _boxes(session) == {"鳳梨酥禮盒": (40, LineStatus.ACTIVE), "蛋黃酥禮盒": (20, LineStatus.ACTIVE)}


def test_an_added_product_is_accepted_on_resend(client, make_template_file, session):
    rows = [row("芋頭酥禮盒", 25, pickup_on=FAR)]
    assert "品項「芋頭酥禮盒」不在商品清單裡" in _post_file(client, rows, make_template_file)

    client.post("/products", data={"kind": "product", "name": "芋頭酥禮盒"})

    assert '<td class="product-name">芋頭酥禮盒</td>' in client.get("/products").text
    assert "收到 1 張喜餅訂單、1 筆訂單明細。" in _post_file(client, rows, make_template_file)
    assert _boxes(session) == {"芋頭酥禮盒": (25, LineStatus.ACTIVE)}
    assert _order(session).lines[0].product_code == "P08"


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "product", "name": "龍鳳"},  # already an alias
        {"kind": "alias", "product_code": "P02", "name": "龍鳳喜餅"},  # already a 品項
        {"kind": "alias", "product_code": "P02", "name": "   "},
        {"kind": "alias", "product_code": "P99", "name": "新名字"},
    ],
)
def test_names_that_clash_or_are_blank_are_refused(client, data):
    resp = client.post("/products", data=data)

    assert resp.status_code == 422
    assert 'class="error"' in resp.text


def test_only_hq_maintains_products_and_cutoff(make_client, session):
    owner = make_client("owner")
    assert owner.get("/products").status_code == 200
    assert "新增品項" not in owner.get("/products").text

    for username in ("owner", "kitchen"):
        c = make_client(username)
        assert c.post("/products", data={"kind": "product", "name": "芋頭酥禮盒"}).status_code == 403
        assert c.post("/settings", data={"cutoff": "3"}).status_code == 403
    assert make_client("kitchen").get("/products").status_code == 403
    assert re.search(r'class="cutoff-days">7<', owner.get("/settings").text)
