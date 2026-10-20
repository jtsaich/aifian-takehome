"""LINE webhook: signed fake payloads in, a stubbed LINE API (content download, reply,
member profile) on the other side. No network."""

from __future__ import annotations

import html
import io
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from bakery import pipeline
from bakery.line import LineApi, LineChannel, sign
from bakery.models import BindingStatus, LineWebhookEvent, Order, StoreBinding, Upload, Uploader
from bakery.reply import PROCESSING_FAILED
from bakery.web.app import create_app
from bakery.web.deps import get_now
from bakery.web.routes.line_webhook import get_line
from conftest import CLEAN_ROWS, NOW, reset_database

SECRET = "test-channel-secret"
TOKEN = "test-access-token"
GROUP = "Cgroup0001"
MOCK = Path(__file__).resolve().parents[1] / "mock_data"
TC01_DAY1 = MOCK / "day1" / "TC01_台中中正店.xlsx"


class FakeLine:
    """The parts of the LINE API the app calls, recording every request."""

    def __init__(self) -> None:
        self.contents: dict[str, bytes] = {}
        self.names: dict[str, str] = {}
        self.unavailable: set[str] = set()  # message ids whose content download fails
        self.downloads: list[str] = []
        self.replies: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        host, path = request.url.host, request.url.path
        if host == "api-data.line.me" and (m := re.fullmatch(r"/v2/bot/message/([^/]+)/content", path)):
            self.downloads.append(m[1])
            if m[1] in self.unavailable:
                return httpx.Response(503)
            return httpx.Response(200, content=self.contents[m[1]])
        if host == "api.line.me" and path == "/v2/bot/message/reply" and request.method == "POST":
            self.replies.append(json.loads(request.content))
            return httpx.Response(200, json={})
        if host == "api.line.me" and (m := re.fullmatch(rf"/v2/bot/group/{GROUP}/member/([^/]+)", path)):
            if m[1] in self.names:
                return httpx.Response(200, json={"displayName": self.names[m[1]], "userId": m[1]})
            return httpx.Response(404)
        return httpx.Response(404)

    @property
    def reply_texts(self) -> list[str]:
        return [r["messages"][0]["text"] for r in self.replies]


@pytest.fixture
def line() -> FakeLine:
    return FakeLine()


@pytest.fixture
def webhook(engine, session_factory, line) -> Iterator[TestClient]:
    """An anonymous client: LINE has no login, only the signature."""
    app = create_app(engine)
    app.dependency_overrides[get_now] = lambda: NOW
    channel = LineChannel(SECRET, LineApi(TOKEN, transport=httpx.MockTransport(line.handle)))
    app.dependency_overrides[get_line] = lambda: channel
    with TestClient(app) as c:
        yield c


def file_event(
    n: int, *, user_id: str | None = "Ustore0001", file_name: str = "TC01.xlsx", redelivery: bool = False
) -> dict:
    source = {"type": "group", "groupId": GROUP}
    if user_id is not None:
        source["userId"] = user_id
    return {
        "type": "message",
        "mode": "active",
        "timestamp": 1792540800000 + n,
        "source": source,
        "webhookEventId": f"01JEVENT{n:018d}",
        "deliveryContext": {"isRedelivery": redelivery},
        "replyToken": f"reply-token-{n}",
        "message": {"type": "file", "id": f"msg{n}", "fileName": file_name, "fileSize": 1234},
    }


def post(client: TestClient, *events: dict, signature: str | None = None) -> httpx.Response:
    body = json.dumps({"destination": "Ubot", "events": list(events)}, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    headers["X-Line-Signature"] = sign(SECRET, body) if signature is None else signature
    return client.post("/line/webhook", content=body, headers=headers)


def send(client: TestClient, line: FakeLine, n: int, content: bytes, **event) -> httpx.Response:
    line.contents[f"msg{n}"] = content
    return post(client, file_event(n, **event))


def test_a_template_file_is_kept_processed_and_answered_with_a_reply(webhook, line, session, clean_file):
    resp = send(webhook, line, 1, clean_file, user_id="Udemo-TC01")

    assert resp.status_code == 200
    upload = session.scalars(select(Upload)).one()
    assert upload.content == clean_file  # the original, downloaded before answering
    assert upload.uploader.line_user_id == "Udemo-TC01"
    assert upload.submitted_by is None  # came from LINE
    assert line.downloads == ["msg1"]
    assert line.replies == [
        {"replyToken": "reply-token-1", "messages": [{"type": "text", "text": upload.reply_text}]}
    ]
    assert upload.reply_text == "台中中正店（TC01）：收到 2 張喜餅訂單、3 筆訂單明細。"
    assert {o.order_no for o in session.scalars(select(Order))} == {"0201", "0202"}


@pytest.mark.parametrize("signature", ["", "bm90LXRoZS1zaWduYXR1cmU=", sign("another-channel", b"{}")])
def test_a_request_without_a_valid_signature_is_rejected(webhook, line, session, clean_file, signature):
    line.contents["msg1"] = clean_file

    resp = post(webhook, file_event(1), signature=signature)

    assert resp.status_code == 400
    assert line.downloads == [] and line.replies == []
    assert session.scalars(select(Upload)).all() == []
    assert session.scalars(select(LineWebhookEvent)).all() == []


def test_a_signed_body_that_was_altered_is_rejected(webhook, line, session, clean_file):
    line.contents["msg1"] = clean_file
    signed_for = json.dumps({"destination": "Ubot", "events": []}).encode()

    resp = post(webhook, file_event(1), signature=sign(SECRET, signed_for))

    assert resp.status_code == 400
    assert session.scalars(select(Upload)).all() == []


def test_without_channel_settings_the_webhook_refuses(engine, session_factory, monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    with TestClient(create_app(engine)) as c:
        assert post(c, file_event(1)).status_code == 503


def test_the_console_verify_request_gets_200(webhook, line):
    assert post(webhook).status_code == 200
    assert line.replies == []


def test_a_redelivered_event_is_processed_only_once(webhook, line, session, clean_file):
    line.contents["msg1"] = clean_file

    first = post(webhook, file_event(1))
    again = post(webhook, file_event(1, redelivery=True))
    and_again = post(webhook, file_event(1))  # a plain duplicate, e.g. after a network retry

    assert (first.status_code, again.status_code, and_again.status_code) == (200, 200, 200)
    assert len(session.scalars(select(Upload)).all()) == 1
    assert line.downloads == ["msg1"]
    assert len(line.replies) == 1
    event = session.get(LineWebhookEvent, file_event(1)["webhookEventId"])
    assert event.upload_id == session.scalars(select(Upload)).one().id


def test_a_file_that_could_not_be_downloaded_is_left_for_redelivery(webhook, line, session, clean_file):
    line.contents["msg1"] = clean_file
    line.unavailable.add("msg1")

    assert post(webhook, file_event(1)).status_code == 500
    assert session.scalars(select(Upload)).all() == []
    assert line.replies == []

    line.unavailable.clear()
    assert post(webhook, file_event(1, redelivery=True)).status_code == 200
    assert len(session.scalars(select(Upload)).all()) == 1
    assert len(line.replies) == 1


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"%PDF-1.7 not a spreadsheet", id="pdf"),
        pytest.param((MOCK / "legacy" / "TC02_台中北屯店_舊訂單.xlsx").read_bytes(), id="xlsx-without-template-cells"),
    ],
)
def test_a_file_that_is_not_a_template_gets_no_reply_and_is_not_kept(webhook, line, session, content):
    resp = send(webhook, line, 1, content, file_name="會議記錄.xlsx")

    assert resp.status_code == 200
    assert line.downloads == ["msg1"]
    assert line.replies == []
    assert session.scalars(select(Upload)).all() == []


def test_a_broken_template_still_gets_a_reply(webhook, line, session, make_template_file):
    """Recognised by its cells, so a 範本 with a wrong 門市代碼 is answered, not ignored."""
    wb = load_workbook(io.BytesIO(make_template_file("TC01", CLEAN_ROWS)))
    wb.active["B1"] = "XX99"
    buf = io.BytesIO()
    wb.save(buf)

    send(webhook, line, 1, buf.getvalue())

    assert line.reply_texts == ["這份檔案沒有收：門市代碼「XX99」不在門市清單裡。請確認範本左上角的門市代碼後再傳一次。"]


def test_a_first_time_uploader_is_recorded_pending_and_told_so(webhook, line, session, clean_file):
    line.names["Unew0001"] = "阿華"

    send(webhook, line, 1, clean_file, user_id="Unew0001")

    first_line, summary = line.reply_texts[0].split("\n", 1)
    assert first_line == "已記錄您為 台中中正店（待總部確認）"
    assert summary == "台中中正店（TC01）：收到 2 張喜餅訂單、3 筆訂單明細。"
    uploader = session.scalars(select(Uploader).where(Uploader.line_user_id == "Unew0001")).one()
    assert uploader.display_name == "阿華"  # so 總部 can tell who to confirm
    assert (uploader.binding.store_code, uploader.binding.status) == ("TC01", BindingStatus.PENDING)
    assert len(session.scalars(select(Order)).all()) == 2  # processed as usual

    send(webhook, line, 2, clean_file, user_id="Unew0001")
    assert not line.reply_texts[1].startswith("已記錄")  # only the first time


def test_a_bound_uploader_sending_another_stores_file_is_processed_with_a_warning(
    webhook, line, session, clean_file
):
    send(webhook, line, 1, clean_file, user_id="Udemo-CH01")

    first_line, summary = line.reply_texts[0].split("\n", 1)
    assert first_line == "注意：您的帳號登記在彰化中華店，這份是台中中正店的檔案。已照常收下，請確認沒有傳錯檔案。"
    assert summary.startswith("台中中正店（TC01）：收到 2 張喜餅訂單")
    assert {o.store_code for o in session.scalars(select(Order))} == {"TC01"}
    assert session.get(StoreBinding, session.scalars(
        select(Uploader.id).where(Uploader.line_user_id == "Udemo-CH01")).one()).store_code == "CH01"


def test_a_file_from_an_account_line_did_not_identify_is_processed(webhook, line, session, clean_file):
    send(webhook, line, 1, clean_file, user_id=None)

    first_line, summary = line.reply_texts[0].split("\n", 1)
    assert first_line == "系統認不出是哪個 LINE 帳號傳的，檔案照常收下，但沒辦法記錄傳檔者。"
    assert summary.startswith("台中中正店（TC01）：收到 2 張喜餅訂單")
    upload = session.scalars(select(Upload)).one()
    assert upload.uploader is None and upload.content == clean_file


def test_a_processing_failure_is_answered_and_the_original_and_reason_kept(
    webhook, line, session, clean_file, monkeypatch
):
    def broken(*args, **kwargs):
        raise RuntimeError("0912-345-678 王小姐")  # library messages can quote cells

    monkeypatch.setattr(pipeline, "merge_orders", broken)

    assert send(webhook, line, 1, clean_file, user_id="Udemo-TC01").status_code == 200

    assert line.reply_texts[0].startswith("這份檔案沒處理成功，總部已收到通知")
    upload = session.scalars(select(Upload)).one()
    assert upload.content == clean_file
    assert upload.failure_reason.startswith("RuntimeError（")
    assert "0912" not in upload.failure_reason and "王" not in upload.failure_reason
    assert session.scalars(select(Order)).all() == []


def test_if_even_the_original_cannot_be_kept_the_store_still_gets_an_answer(
    webhook, line, session, clean_file, monkeypatch
):
    def database_down(*args, **kwargs):
        raise ConnectionError

    monkeypatch.setattr("bakery.line_webhook.process_upload", database_down)

    assert send(webhook, line, 1, clean_file).status_code == 200
    assert line.reply_texts == [PROCESSING_FAILED]


def test_logs_never_carry_names_or_phones(webhook, line, session, monkeypatch, make_template_file, caplog):
    caplog.set_level(logging.DEBUG)
    line.names["Unew0001"] = "林阿華"
    rows = [list(r) for r in CLEAN_ROWS]
    rows[2][2] = "0912-34"  # a phone warning that quotes the number in the reply
    content = make_template_file("TC01", rows)

    send(webhook, line, 1, content, user_id="Unew0001", file_name="王小姐 0912-345-678.xlsx")

    def broken(*args, **kwargs):
        raise ValueError("李先生 04-2345-6789")

    monkeypatch.setattr(pipeline, "merge_orders", broken)
    send(webhook, line, 2, content, user_id="Unew0001", file_name="李先生.xlsx")

    assert "0912-34" in line.reply_texts[0]  # the reply may quote it; the logs may not
    assert caplog.records, "expected the webhook to log something"
    for secret in ("王小姐", "李先生", "0912-345-678", "0912-34", "04-2345-6789", "陳志豪", "林阿華"):
        assert secret not in caplog.text, secret


def _demo_page_reply(client: TestClient, uploader: str, path: Path) -> str:
    page = client.post(
        "/demo/upload",
        data={"uploader_line_id": uploader},
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    ).text
    return html.unescape(re.search(r'<div class="reply">(.*?)</div>', page, re.S)[1])


@pytest.mark.parametrize(
    ("uploader", "path"),
    [
        pytest.param("Unew0001", TC01_DAY1, id="first-time-uploader"),
        pytest.param("Udemo-CH01", TC01_DAY1, id="other-store-uploader"),
        pytest.param("Udemo-NT01", MOCK / "day1" / "NT01_草屯和平店.xlsx", id="bound-uploader"),
    ],
)
def test_the_line_reply_is_identical_to_the_simulated_upload_page(
    engine, webhook, line, make_client, uploader, path
):
    send(webhook, line, 1, path.read_bytes(), user_id=uploader, file_name=path.name)
    (line_reply,) = line.reply_texts

    reset_database(engine)  # the same starting point for the demo page
    page_reply = _demo_page_reply(make_client("hq-lin"), uploader, path)

    assert page_reply == line_reply
