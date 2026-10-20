"""process_upload: the one entry point every upload source (demo page, LINE webhook) calls."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from bakery.models import LineStatus, Order, Upload
from bakery.pipeline import process_upload

DEMO_UPLOADER = "Udemo-TC01"


def _orders(session) -> dict[str, Order]:
    return {o.order_no: o for o in session.scalars(select(Order))}


def _lines(order: Order) -> dict[str, tuple[int, str | None, LineStatus]]:
    return {ln.product.name: (ln.quantity, ln.note, ln.status) for ln in order.lines}


def _upload(session, now, file_bytes, *, uploader=DEMO_UPLOADER, filename="TC01.xlsx"):
    return process_upload(
        session, uploader_line_id=uploader, filename=filename, file_bytes=file_bytes, now=now
    )


def test_clean_file_stores_every_order_and_line_with_its_content(session, now, clean_file):
    _upload(session, now, clean_file)

    orders = _orders(session)
    assert set(orders) == {"0201", "0202"}

    o = orders["0201"]
    assert (o.store_code, o.orderer_name, o.phone) == ("TC01", "王小姐", "0912-345-678")
    assert (o.received_on, o.pickup_on, o.banquet_on) == (
        date(2026, 10, 20),
        date(2026, 11, 28),
        date(2026, 11, 29),
    )
    assert (o.couple_names, o.taken_by) == ("陳志豪、林佳蓉", "美玲")
    assert _lines(o) == {
        "龍鳳喜餅": (120, "要提袋", LineStatus.ACTIVE),
        "鳳梨酥禮盒": (60, None, LineStatus.ACTIVE),
    }

    o = orders["0202"]
    assert (o.orderer_name, o.phone, o.banquet_on, o.taken_by) == ("李先生", "04-2345-6789", None, None)
    assert o.pickup_on == date(2026, 12, 5)
    assert _lines(o) == {"綠豆椪禮盒": (40, None, LineStatus.ACTIVE)}


def test_reply_names_the_store_and_counts_orders_and_lines(session, now, clean_file):
    result = _upload(session, now, clean_file)

    assert result.reply_text == "台中中正店（TC01）：收到 2 張喜餅訂單、3 筆訂單明細。"


def test_original_file_is_kept_byte_for_byte_with_uploader_and_time(session, now, clean_file):
    result = _upload(session, now, clean_file, filename="門市檔案.xlsx")

    upload = session.get(Upload, result.upload_id)
    assert upload.content == clean_file
    assert upload.filename == "門市檔案.xlsx"
    assert upload.uploader.line_user_id == DEMO_UPLOADER
    assert upload.received_at == now
    assert upload.store_code == "TC01"
    assert upload.reply_text == result.reply_text


@pytest.mark.parametrize(
    "tamper",
    [
        lambda uid: update(Upload).where(Upload.id == uid).values(content=b"tampered"),
        lambda uid: update(Upload).where(Upload.id == uid).values(filename="other.xlsx"),
        lambda uid: delete(Upload).where(Upload.id == uid),
    ],
    ids=["content", "filename", "delete"],
)
def test_original_file_cannot_be_changed_or_deleted(session, now, clean_file, tamper):
    result = _upload(session, now, clean_file)

    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(tamper(result.upload_id))
    session.rollback()
    assert session.get(Upload, result.upload_id).content == clean_file


def test_unknown_uploader_is_recorded_on_first_upload(session, now, clean_file):
    result = _upload(session, now, clean_file, uploader="U-first-time")

    assert session.get(Upload, result.upload_id).uploader.line_user_id == "U-first-time"


def test_reuploading_an_order_updates_it_and_keeps_lines_missing_from_the_file(
    session, now, clean_file, make_template_file
):
    _upload(session, now, clean_file, filename="day1.xlsx")
    # Same 單號 0201 with only the 龍鳳喜餅 row, now 150 盒.
    # ADR 0001: the 鳳梨酥禮盒 row missing from this file means nothing.
    again = make_template_file(
        "TC01",
        [
            ("0201", "王小姐", "0912-345-678", date(2026, 10, 20), date(2026, 11, 28),
             date(2026, 11, 29), "陳志豪、林佳蓉", "美玲", "龍鳳喜餅", 150, "要提袋", None),
        ],
    )
    _upload(session, now, again, filename="day2.xlsx")

    orders = _orders(session)
    assert set(orders) == {"0201", "0202"}
    assert _lines(orders["0201"]) == {
        "龍鳳喜餅": (150, "要提袋", LineStatus.ACTIVE),
        "鳳梨酥禮盒": (60, None, LineStatus.ACTIVE),
    }
