"""門市綁定: recorded from a 傳檔者's first file, confirmed by 總部 on the web, and
checked on every upload whichever way the file arrives (LINE or the demo page)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from bakery import pipeline
from bakery.models import BindingStatus, Order, StoreBinding, Upload, Uploader
from bakery.pipeline import process_upload

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(session, now, file_bytes: bytes, uploader: str | None):
    return process_upload(
        session, uploader_line_id=uploader, filename="f.xlsx", file_bytes=file_bytes, now=now
    )


def binding_of(session, line_user_id: str) -> StoreBinding | None:
    uploader = session.scalars(select(Uploader).where(Uploader.line_user_id == line_user_id)).one()
    session.refresh(uploader)
    return uploader.binding


def test_first_file_records_a_pending_binding_and_says_so_first(session, now, clean_file):
    result = upload(session, now, clean_file, "Unew0001")

    assert result.reply_text.splitlines()[0] == "已記錄您為 台中中正店（待總部確認）"
    assert result.reply_text.splitlines()[1] == "台中中正店（TC01）：收到 2 張喜餅訂單、3 筆訂單明細。"
    binding = binding_of(session, "Unew0001")
    assert (binding.store_code, binding.status) == ("TC01", BindingStatus.PENDING)
    assert len(session.scalars(select(Order)).all()) == 2


def test_later_files_of_the_same_store_carry_no_binding_line(session, now, clean_file):
    upload(session, now, clean_file, "Unew0001")

    again = upload(session, now, clean_file, "Unew0001")

    assert again.reply_text.startswith("台中中正店（TC01）：")


def test_a_refused_file_records_no_binding(session, now, make_template_file):
    """No 門市 known, nothing to bind: the first file that names a 門市 records it."""
    result = upload(session, now, b"not a spreadsheet", "Unew0001")

    assert result.reply_text.startswith("這份檔案沒有收：")
    assert binding_of(session, "Unew0001") is None

    later = upload(session, now, make_template_file("CH01", []), "Unew0001")
    assert later.reply_text.startswith("已記錄您為 彰化中華店（待總部確認）")


def test_another_stores_file_is_processed_with_a_warning(session, now, clean_file):
    result = upload(session, now, clean_file, "Udemo-CH01")

    assert result.reply_text.splitlines()[0] == (
        "注意：您的帳號登記在彰化中華店，這份是台中中正店的檔案。已照常收下，請確認沒有傳錯檔案。"
    )
    assert {o.store_code for o in session.scalars(select(Order))} == {"TC01"}
    assert binding_of(session, "Udemo-CH01").store_code == "CH01"  # the binding is not moved


def test_a_pending_uploader_sending_another_stores_file_is_warned_too(session, now, clean_file, make_template_file):
    upload(session, now, make_template_file("CH01", []), "Unew0001")

    result = upload(session, now, clean_file, "Unew0001")

    assert result.reply_text.startswith("注意：您的帳號登記在彰化中華店，這份是台中中正店的檔案。")


def test_a_store_can_have_several_uploaders(session, now, clean_file):
    shared = upload(session, now, clean_file, "Udemo-TC01")
    personal = upload(session, now, clean_file, "Udemo-TC01-meiling")

    assert shared.reply_text.startswith("台中中正店（TC01）：")
    assert personal.reply_text.startswith("已記錄您為 台中中正店（待總部確認）")
    assert binding_of(session, "Udemo-TC01").store_code == binding_of(session, "Udemo-TC01-meiling").store_code


def test_an_unidentified_sender_is_processed_and_told_the_account_was_not_recorded(session, now, clean_file):
    result = upload(session, now, clean_file, None)

    assert result.reply_text.splitlines()[0] == "系統認不出是哪個 LINE 帳號傳的，檔案照常收下，但沒辦法記錄傳檔者。"
    assert session.get(Upload, result.upload_id).uploader is None
    assert len(session.scalars(select(Order)).all()) == 2


def test_a_processing_failure_records_no_binding_and_keeps_the_reason(session, now, clean_file, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("王小姐")

    monkeypatch.setattr(pipeline, "merge_orders", broken)

    result = upload(session, now, clean_file, "Unew0001")

    assert result.reply_text == "這份檔案沒處理成功，總部已收到通知。原檔已經保存，不用重傳。\n\n廚房彙總：/kitchen"
    stored = session.get(Upload, result.upload_id)
    assert stored.content == clean_file
    assert re.fullmatch(r"KeyError（\w+\.py:\d+ \w+）", stored.failure_reason)
    assert binding_of(session, "Unew0001") is None


def test_the_upload_pages_show_a_failure_and_its_reason(client, session, clean_file, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("x")

    monkeypatch.setattr(pipeline, "merge_orders", broken)
    client.post(
        "/demo/upload", data={"uploader_line_id": "Udemo-TC01"}, files={"file": ("f.xlsx", clean_file, XLSX)}
    )
    reason = session.scalars(select(Upload.failure_reason)).one()

    assert "處理失敗" in client.get("/uploads").text
    assert reason in client.get("/uploads/1").text


def test_the_demo_page_uses_the_same_binding_check(client, clean_file):
    page = client.post(
        "/demo/upload",
        data={"uploader_line_id": "Udemo-TC01-meiling"},
        files={"file": ("TC01.xlsx", clean_file, XLSX)},
    ).text

    assert re.search(r'<div class="reply">已記錄您為 台中中正店（待總部確認）\n台中中正店（TC01）', page)


# ------------------------------------------------------------------ confirming on the web


@pytest.fixture
def pending(session, now, clean_file) -> int:
    """美玲 has sent her first file: a pending binding to TC01. Returns her uploader id."""
    upload(session, now, clean_file, "Udemo-TC01-meiling")
    return binding_of(session, "Udemo-TC01-meiling").uploader_id


def test_hq_sees_pending_bindings_first(client, pending):
    html = client.get("/bindings").text

    rows = re.findall(r'<tr class="binding (\w+)">', html)
    assert rows[0] == "pending"
    assert rows.count("confirmed") == 6  # the seeded store accounts
    assert "美玲（台中中正店）" in html and "待總部確認" in html


def test_hq_confirms_a_binding_and_the_confirmation_names_them(client, session, pending, now):
    resp = client.post("/bindings", data={"uploader_id": pending, "store_code": "TC01"})

    assert resp.url.path == "/bindings"
    binding = session.get(StoreBinding, pending)
    session.refresh(binding)
    assert binding.status == BindingStatus.CONFIRMED
    assert binding.confirmed_by.username == "hq-lin"
    assert binding.confirmed_at == now
    assert "已確認（林雅文（總部）" in resp.text


def test_hq_can_correct_the_store_while_confirming(client, session, pending, now, clean_file):
    client.post("/bindings", data={"uploader_id": pending, "store_code": "TC02"})

    result = upload(session, now, clean_file, "Udemo-TC01-meiling")

    assert binding_of(session, "Udemo-TC01-meiling").store_code == "TC02"
    assert result.reply_text.startswith("注意：您的帳號登記在台中北屯店，這份是台中中正店的檔案。")


@pytest.mark.parametrize("username", ["owner", "kitchen"])
def test_only_hq_may_confirm(make_client, session, pending, username):
    resp = make_client(username).post("/bindings", data={"uploader_id": pending, "store_code": "TC01"})

    assert resp.status_code == 403
    session.expire_all()
    assert session.get(StoreBinding, pending).status == BindingStatus.PENDING


def test_the_owner_sees_bindings_without_confirm_buttons(make_client, pending):
    html = make_client("owner").get("/bindings").text

    assert "美玲（台中中正店）" in html
    assert 'action="/bindings"' not in html


def test_confirming_an_unknown_binding_or_store_is_refused(client, pending):
    assert client.post("/bindings", data={"uploader_id": 9999, "store_code": "TC01"}).status_code == 404
    assert client.post("/bindings", data={"uploader_id": pending, "store_code": "XX99"}).status_code == 404


def test_the_seeded_demo_store_accounts_start_confirmed(session):
    confirmed = session.scalars(select(StoreBinding).where(StoreBinding.status == BindingStatus.CONFIRMED)).all()

    assert sorted(b.store_code for b in confirmed) == ["CH01", "CH02", "NT01", "TC01", "TC02", "TC03"]
