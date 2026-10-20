"""The day-2 mock files (修改與重傳), each sent after its day-1 file: new, unchanged and
changed orders, 修改類型 and replies must match the 對照表 (mock_data/expectations.json).

PENDING-07: the 修改截止點 rule is ticket 07. Until then a production-affecting change
past the cutoff (0106) still applies directly, so its 「已過截止點，待總部確認」 outcome and
the summary's 待確認 count that includes it are checked only by the strict xfail test at
the bottom, which starts passing (and so fails as XPASS) once 07 lands.
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
CUTOFF_SUFFIX = "（已過截止點，待總部確認）"


def _pending_07(change: dict) -> bool:
    """Waits for 總部 only because of the 修改截止點 (ticket 07)."""
    return change["past_cutoff"] and change["outcome"] == "pending" and change["kinds"] != ["suspected_reuse"]


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


def test_changes_apply_or_wait_as_the_table_says_except_the_cutoff(processed):
    expected, result = processed

    for actual, want in zip(result.outcome.changes, expected["changes"], strict=True):
        if _pending_07(want):
            assert actual.decision == ChangeDecision.APPLIED, "PENDING-07: cutoff not implemented yet"
            continue
        wanted = ChangeDecision.APPLIED if want["outcome"] == "applied" else ChangeDecision.HELD
        assert actual.decision == wanted, want["order_no"]


def test_reply_matches_the_table_except_the_cutoff(processed):
    expected, result = processed
    pending_07 = sum(1 for c in expected["changes"] if _pending_07(c))
    summary = expected["reply_summary"]
    if pending_07:
        held = sum(1 for c in expected["changes"] if c["outcome"] == "pending")
        # PENDING-07: 待確認 that come from the cutoff are not counted yet.
        summary = summary.replace(f"其中 {held} 張", f"其中 {held - pending_07} 張")

    assert result.reply_text.startswith(summary)
    for change in expected["changes"]:
        line = change["reply"]
        if _pending_07(change):
            line = line.removesuffix(CUTOFF_SUFFIX)  # PENDING-07
        assert f"・{line}" in result.reply_text, change["order_no"]
    for finding in expected["findings"]:
        assert finding["reply"] in result.reply_text


def test_held_orders_keep_their_day1_content(processed, session):
    expected, result = processed
    held = [c["order_no"] for c in expected["changes"] if c["kinds"] == ["suspected_reuse"]]

    for order_no in held:
        order = session.scalar(
            select(Order).where(Order.store_code == expected["store_code"], Order.order_no == order_no)
        )
        reuse = next(c for c in expected["changes"] if c["order_no"] == order_no)
        phone = next(d for d in reuse["diffs"] if d["field"] == "電話")
        assert order.phone == phone["old"]


@pytest.mark.xfail(strict=True, reason="PENDING-07: 修改截止點 / 待確認 is ticket 07")
def test_reply_matches_the_table_including_the_cutoff(processed):
    expected, result = processed
    if not any(_pending_07(c) for c in expected["changes"]):
        pytest.xfail("no cutoff case in this file")  # nothing pending here; keeps strict mode honest

    assert result.reply_text.startswith(expected["reply_summary"])
    for change in expected["changes"]:
        assert f"・{change['reply']}" in result.reply_text, change["order_no"]
