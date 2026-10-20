"""修改: a 單號 already on record sent again. Unchanged is silent, a change is classified,
applied (or held when it looks like a reused 單號), logged append-only, and auditable."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from bakery.models import Change, ChangeEntry, ChangeField, LineStatus, Order, Upload
from bakery.pipeline import process_upload

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ORDER = {
    "order_no": "0301",
    "orderer_name": "王小姐",
    "phone": "0912-345-678",
    "received_on": date(2026, 10, 20),
    "pickup_on": date(2026, 11, 28),
    "banquet_on": date(2026, 11, 29),
    "couple_names": "陳志豪、林佳蓉",
    "taken_by": "美玲",
}


def row(product: str, quantity: int, *, note=None, status=None, **order) -> tuple:
    """One 範本 row of 單號 0301 (or `order_no=`), order fields overridable."""
    o = {**ORDER, **order}
    return (
        o["order_no"], o["orderer_name"], o["phone"], o["received_on"], o["pickup_on"],
        o["banquet_on"], o["couple_names"], o["taken_by"], product, quantity, note, status,
    )


DAY1 = [row("龍鳳喜餅", 80), row("鳳梨酥禮盒", 40)]


@pytest.fixture
def send(session, now, make_template_file):
    """Send rows as a TC01 file `day` days after day 1."""

    def send(rows, *, day: int = 0, uploader: str = "Udemo-TC01"):
        return process_upload(
            session,
            uploader_line_id=uploader,
            filename=f"TC01_day{day + 1}.xlsx",
            file_bytes=make_template_file("TC01", rows),
            now=now + timedelta(days=day),
        )

    return send


def _order(session, order_no="0301") -> Order:
    order = session.scalar(select(Order).where(Order.order_no == order_no))
    session.refresh(order)
    return order


def _lines(order: Order) -> dict[str, tuple[int, LineStatus]]:
    return {ln.product.name: (ln.quantity, ln.status) for ln in order.lines}


def _changes(session, upload_id: int) -> list[Change]:
    return list(session.scalars(select(Change).where(Change.upload_id == upload_id)))


UNCHANGED_REPLY = "台中中正店（TC01）：這份檔案的內容之前都收過了，沒有新單，也沒有修改。"


def test_a_row_missing_from_the_file_is_not_a_cancel(session, send):
    send([*DAY1, row("綠豆椪禮盒", 50, order_no="0302")])

    # 0301 comes back without its 鳳梨酥禮盒 row; 0302 doesn't come back at all.
    result = send([row("龍鳳喜餅", 80)], day=1)

    assert _lines(_order(session)) == {
        "龍鳳喜餅": (80, LineStatus.ACTIVE),
        "鳳梨酥禮盒": (40, LineStatus.ACTIVE),
    }
    assert _lines(_order(session, "0302")) == {"綠豆椪禮盒": (50, LineStatus.ACTIVE)}
    assert result.reply_text == UNCHANGED_REPLY
    assert _changes(session, result.upload_id) == []


def test_identical_resend_does_nothing_and_says_nothing_about_those_orders(session, send):
    soon = [row("龍鳳喜餅", 80, pickup_on=date(2026, 10, 23))]  # too soon: warned on day 1
    first = send(soon)
    assert "已先收下" in first.reply_text

    again = send(soon)

    assert again.reply_text == UNCHANGED_REPLY
    assert _changes(session, again.upload_id) == []


def test_same_phone_written_differently_is_not_a_change(session, send):
    send(DAY1)

    result = send([row("龍鳳喜餅", 80, phone="0912345678"), row("鳳梨酥禮盒", 40, phone="0912345678")])

    assert result.reply_text == UNCHANGED_REPLY


@pytest.mark.parametrize(
    ("day2", "reply_line"),
    [
        pytest.param(
            [row("龍鳳喜餅", 120), row("鳳梨酥禮盒", 40)],
            "單號 0301：追加，龍鳳喜餅 80→120 盒",
            id="追加",
        ),
        pytest.param(
            [row("綠豆椪禮盒", 30)],
            "單號 0301：追加，新增綠豆椪禮盒 30 盒",
            id="追加-新品項",
        ),
        pytest.param(
            [row("鳳梨酥禮盒", 20)],
            "單號 0301：減量，鳳梨酥禮盒 40→20 盒",
            id="減量",
        ),
        pytest.param(
            [row("龍鳳喜餅", 80, pickup_on=date(2026, 12, 5))],
            "單號 0301：改取貨日，2026/11/28→2026/12/05",
            id="改取貨日",
        ),
        pytest.param(
            [row("龍鳳喜餅", 80, status="取消"), row("鳳梨酥禮盒", 40, status="取消")],
            "單號 0301：取消，龍鳳喜餅 80 盒、鳳梨酥禮盒 40 盒不再生產",
            id="取消",
        ),
        pytest.param(
            [row("龍鳳喜餅", 80, couple_names="王大明、李小華")],
            "單號 0301：資料更正，新人姓名 陳志豪、林佳蓉→王大明、李小華",
            id="資料更正",
        ),
        pytest.param(
            [row("龍鳳喜餅", 80, phone="0933-222-111")],
            "單號 0301：資料更正，電話已更新",
            id="資料更正-只改電話",
        ),
        pytest.param(
            [row("龍鳳喜餅", 80, banquet_on=None, note="要提袋")],
            "單號 0301：資料更正，宴客日 2026/11/29→空白；龍鳳喜餅 備註 空白→要提袋",
            id="資料更正-宴客日與備註",
        ),
        pytest.param(
            [row("龍鳳喜餅", 120, pickup_on=date(2026, 12, 5))],
            "單號 0301：追加＋改取貨日，龍鳳喜餅 80→120 盒；取貨日 2026/11/28→2026/12/05",
            id="追加＋改取貨日",
        ),
        pytest.param(
            [row("龍鳳喜餅", 100, taken_by="志豪"), row("鳳梨酥禮盒", 20, status="取消", taken_by="志豪")],
            "單號 0301：追加＋取消＋資料更正，龍鳳喜餅 80→100 盒；鳳梨酥禮盒 40 盒不再生產；接單人 美玲→志豪",
            id="追加＋取消＋資料更正",
        ),
    ],
)
def test_change_is_classified_applied_and_explained(session, send, day2, reply_line):
    send(DAY1)

    result = send(day2, day=1)

    assert result.reply_text.startswith("台中中正店（TC01）：修改 1 張。")
    assert f"・{reply_line}" in result.reply_text
    # Applied: the same file again is now identical to what is on record.
    assert send(day2, day=2).reply_text == UNCHANGED_REPLY


def test_cancel_marks_lines_cancelled_and_reduce_keeps_the_new_count(session, send):
    send(DAY1)

    send([row("龍鳳喜餅", 80, status="取消"), row("鳳梨酥禮盒", 25)], day=1)

    assert _lines(_order(session)) == {
        "龍鳳喜餅": (80, LineStatus.CANCELLED),
        "鳳梨酥禮盒": (25, LineStatus.ACTIVE),
    }


def test_a_cancelled_line_back_in_production_is_an_addition(session, send):
    send([row("龍鳳喜餅", 80, status="取消")])

    result = send([row("龍鳳喜餅", 80)], day=1)

    assert "・單號 0301：追加，龍鳳喜餅 恢復生產 80 盒" in result.reply_text
    assert _lines(_order(session)) == {"龍鳳喜餅": (80, LineStatus.ACTIVE)}


def test_new_and_changed_orders_are_counted_apart(session, send):
    send(DAY1)

    result = send([row("龍鳳喜餅", 90), row("綠豆椪禮盒", 50, order_no="0302")], day=1)

    assert result.reply_text.startswith("台中中正店（TC01）：新單 1 張；修改 1 張。")


@pytest.mark.parametrize(
    ("day2", "what"),
    [
        pytest.param(
            [row("綠豆椪禮盒", 60, phone="0940-720-754", orderer_name="許筱涵", pickup_on=date(2026, 12, 12))],
            "取貨日和品項",
            id="取貨日和品項",
        ),
        pytest.param(
            [row("龍鳳喜餅", 80, phone="0940-720-754", pickup_on=date(2026, 12, 12))],
            "取貨日",
            id="取貨日",
        ),
        pytest.param(
            [row("龍鳳喜餅", 200, phone="0940-720-754")],
            "盒數",
            id="盒數",
        ),
    ],
)
def test_suspected_reuse_of_an_order_no_is_flagged_and_not_applied(session, send, day2, what):
    send(DAY1)

    result = send(day2, day=1)

    assert result.reply_text.startswith("台中中正店（TC01）：修改 1 張，其中 1 張待總部確認。")
    assert (
        f"・單號 0301：電話跟之前不同，{what}也變了，可能是兩張不同的單用了同一個單號。"
        "這張單先照舊，待總部確認；請檢查單號有沒有重複。"
    ) in result.reply_text
    order = _order(session)
    assert (order.phone, order.pickup_on, order.orderer_name) == (
        "0912-345-678", date(2026, 11, 28), "王小姐"
    )
    assert _lines(order) == {"龍鳳喜餅": (80, LineStatus.ACTIVE), "鳳梨酥禮盒": (40, LineStatus.ACTIVE)}
    [change] = _changes(session, result.upload_id)
    assert (change.kinds, change.decision) == (["suspected_reuse"], "held")


def test_change_log_records_upload_uploader_time_field_old_and_new(session, send, now):
    first = send(DAY1)
    second = send([row("龍鳳喜餅", 120), row("鳳梨酥禮盒", 40)], day=1, uploader="Udemo-TC01-meiling")

    log = session.scalars(
        select(Change).join(Change.order).where(Order.order_no == "0301").order_by(Change.id)
    ).all()

    assert [(c.upload_id, c.is_new_order, c.kinds, c.decision) for c in log] == [
        (first.upload_id, True, [], "applied"),
        (second.upload_id, False, ["add_qty"], "applied"),
    ]
    change = log[1]
    assert change.upload.uploader.line_user_id == "Udemo-TC01-meiling"
    assert change.upload.received_at == now + timedelta(days=1)
    assert [(e.field, e.product_code and e.product.name, e.old_value, e.new_value) for e in change.entries] == [
        (ChangeField.QUANTITY, "龍鳳喜餅", "80", "120")
    ]
    # The 新單 entry holds the order as first received.
    first_entries = {(e.field, e.product and e.product.name): e.new_value for e in log[0].entries}
    assert first_entries[(ChangeField.PICKUP_ON, None)] == "2026-11-28"
    assert first_entries[(ChangeField.QUANTITY, "龍鳳喜餅")] == "80"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda: update(Change).values(decision="held"),
        lambda: delete(Change),
        lambda: update(ChangeEntry).values(new_value="999"),
        lambda: delete(ChangeEntry),
    ],
    ids=["update-change", "delete-change", "update-entry", "delete-entry"],
)
def test_change_log_cannot_be_rewritten_or_deleted(session, send, tamper):
    send(DAY1)
    send([row("龍鳳喜餅", 120)], day=1)

    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(tamper())
    session.rollback()
    assert len(session.scalars(select(ChangeEntry)).all()) > 0


def test_a_rejected_file_logs_no_change(session, send, now):
    send(DAY1)
    bad = process_upload(
        session, uploader_line_id="Udemo-TC01", filename="x.xlsx", file_bytes=b"not excel", now=now
    )

    assert _changes(session, bad.upload_id) == []
    assert session.get(Upload, bad.upload_id).reply_text.startswith("這份檔案沒有收")


def _post(client, rows, make_template_file, uploader="Udemo-TC01"):
    resp = client.post(
        "/demo/upload",
        data={"uploader_line_id": uploader},
        files={"file": ("TC01.xlsx", make_template_file("TC01", rows), XLSX)},
    )
    assert resp.status_code == 200


def test_audit_page_shows_full_history_and_is_linked_from_master_list(client, make_template_file):
    _post(client, DAY1, make_template_file)
    _post(client, [row("龍鳳喜餅", 120)], make_template_file, uploader="Udemo-TC01-meiling")
    _post(client, [row("龍鳳喜餅", 120, phone="0940-720-754", pickup_on=date(2026, 12, 12))], make_template_file)

    master = client.get("/orders").text
    link = re.search(r'<td class="order-no"><a href="(/orders/\d+)">0301</a>', master)[1]
    html = client.get(link).text

    assert "台中中正店 單號 0301" in html
    sections = html.split('<section class="change">')[1:]
    assert len(sections) == 3
    assert "新單" in sections[0] and "上傳 #1" in sections[0] and "台中中正店 門市帳號" in sections[0]
    assert "追加" in sections[1] and "美玲（台中中正店）" in sections[1]
    assert re.search(r"<td>盒數</td>\s*<td>龍鳳喜餅</td>\s*<td>80</td>\s*<td>120</td>", sections[1])
    assert "疑似單號重複使用" in sections[2] and "未套用" in sections[2]
    assert re.search(r"<td>取貨日</td>\s*<td></td>\s*<td>2026/11/28</td>\s*<td>2026/12/12</td>", sections[2])


def test_change_from_an_unidentified_line_account_is_logged_and_auditable(
    client, session, send, now, make_template_file
):
    send(DAY1)
    result = process_upload(
        session,
        uploader_line_id=None,
        filename="TC01.xlsx",
        file_bytes=make_template_file("TC01", [row("龍鳳喜餅", 120)]),
        now=now,
    )
    [change] = _changes(session, result.upload_id)

    html = client.get(f"/orders/{change.order_id}").text

    assert "・單號 0301：追加，龍鳳喜餅 80→120 盒" in result.reply_text
    assert "（認不出的 LINE 帳號）" in html


def test_kitchen_master_list_has_no_audit_links(make_client, client, make_template_file):
    _post(client, DAY1, make_template_file)

    html = make_client("kitchen").get("/orders").text

    assert 'href="/orders/' not in html
    assert '<td class="order-no">0301</td>' in html


def test_audit_page_for_an_unknown_order_is_not_found(client):
    assert client.get("/orders/999").status_code == 404
