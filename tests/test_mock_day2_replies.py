"""The day-2 mock files (修改與重傳), each sent after its day-1 file: new, unchanged and
changed orders, 修改類型, what applies and what waits for 總部 (修改截止點 and 疑似單號重複使用),
and replies must match the 對照表 (mock_data/expectations.json).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import select

from bakery.clock import TAIPEI
from bakery.models import ChangeDecision, Order
from bakery.pipeline import process_upload

MOCK = Path(__file__).resolve().parents[1] / "mock_data"
MANIFEST = json.loads((MOCK / "expectations.json").read_text())
FILES = {f["file"]: f for f in MANIFEST["files"]}
DAY2 = [f for f in MANIFEST["files"] if f["stage"] == "day2"]
DAY2_NOW = datetime.combine(date.fromisoformat(MANIFEST["day2"]), time(10, 0), tzinfo=TAIPEI)


def _send(session, entry: dict, now: datetime):
    path = MOCK / entry["file"]
    return process_upload(
        session,
        uploader_line_id=f"Udemo-{entry['store_code']}",
        filename=path.name,
        file_bytes=path.read_bytes(),
        now=now,
    )


@pytest.fixture(params=DAY2, ids=[f["file"] for f in DAY2])
def processed(request, session, now):
    expected = request.param
    for earlier in expected["process_after"]:
        assert FILES[earlier]["upload_on"] == now.date().isoformat()
        _send(session, FILES[earlier], now)
    assert expected["upload_on"] == DAY2_NOW.date().isoformat()
    return expected, _send(session, expected, DAY2_NOW)


def test_new_unchanged_and_changed_orders_match(processed):
    expected, result = processed
    outcome = result.outcome

    assert list(outcome.new_order_nos) == expected["new_orders"]
    assert list(outcome.unchanged_order_nos) == expected["unchanged_orders"]
    assert [c.order_no for c in outcome.changes] == [c["order_no"] for c in expected["changes"]]
    assert outcome.order_count == len(expected["accepted_orders"])
    assert outcome.line_count == expected["accepted_lines"]


def test_change_kinds_and_logged_diffs_match(processed):
    expected, result = processed

    for actual, want in zip(result.outcome.changes, expected["changes"], strict=True):
        assert [k.value for k in actual.kinds] == want["kinds"], want["order_no"]
        # The 對照表 lists the diffs that make the case; the log may hold more (e.g. 新人姓名).
        logged = {(d.field.value, d.product_name, d.old, d.new) for d in actual.diffs}
        for diff in want["diffs"]:
            assert _logged_form(diff) in logged, (want["order_no"], diff)


def _logged_form(diff: dict) -> tuple:
    field = {"盒數": "quantity", "取貨日": "pickup_on", "宴客日": "banquet_on", "電話": "phone",
             "訂購人姓名": "orderer_name", "新人姓名": "couple_names", "狀態": "status"}[diff["field"]]
    old, new = diff["old"] or None, diff["new"]
    if field == "quantity" and old == "0":
        old = None  # a 品項 the order didn't have
    if field == "status":
        old, new = "active", {"取消": "cancelled"}[new]
    return field, diff["product"], old, new


def test_changes_apply_or_wait_as_the_table_says(processed):
    expected, result = processed

    for actual, want in zip(result.outcome.changes, expected["changes"], strict=True):
        wanted = ChangeDecision.APPLIED if want["outcome"] == "applied" else ChangeDecision.HELD
        assert actual.decision == wanted, want["order_no"]


def test_reply_matches_the_table(processed):
    expected, result = processed

    assert result.reply_text.startswith(expected["reply_summary"])
    for change in expected["changes"]:
        assert f"・{change['reply']}" in result.reply_text, change["order_no"]
    for finding in expected["findings"]:
        assert finding["reply"] in result.reply_text


def test_held_orders_keep_their_day1_content(processed, session):
    expected, _ = processed

    for change in (c for c in expected["changes"] if c["outcome"] == "pending"):
        order = session.scalar(
            select(Order).where(Order.store_code == expected["store_code"], Order.order_no == change["order_no"])
        )
        boxes = {line.product.name: str(line.quantity) for line in order.lines}
        for diff in change["diffs"]:
            if diff["field"] == "電話":
                assert order.phone == diff["old"], change["order_no"]
            if diff["field"] == "盒數":
                assert boxes.get(diff["product"], "0") == diff["old"], change["order_no"]
