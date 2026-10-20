"""LINE webhook events → process_upload → reply, all before the HTTP response.

Cloud Run throttles the CPU once the response is sent, and the reply token is good
for one minute, so each file is downloaded, processed and answered inline.

- Each event is taken once, by webhookEventId (LINE may deliver it again).
- Only 範本 files are answered (bakery.parsing.is_template_file); anything else sent
  to the group gets no reply and is not kept.
- Logs carry event, message and upload ids only: never file names, cell content
  or LINE display names.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bakery.line import LineApi
from bakery.models import LineWebhookEvent, Uploader
from bakery.parsing import is_template_file
from bakery.pipeline import keep_failed_original, process_upload
from bakery.reply import download_failed_reply, processing_failed_reply

log = logging.getLogger(__name__)


def handle_events(session: Session, api: LineApi, events: Iterable[Mapping[str, Any]], now: datetime) -> None:
    """Handle every file message. Each one is answered: LINE redelivery is off by default,
    so an error response would lose the file without a word."""
    for event in events:
        message = event.get("message") or {}
        if event.get("type") == "message" and message.get("type") == "file":
            _handle_file(session, api, event, message, now)


def _handle_file(
    session: Session, api: LineApi, event: Mapping[str, Any], message: Mapping[str, Any], now: datetime
) -> None:
    event_id = event.get("webhookEventId")
    if event_id is not None and not _claim(session, event_id, now):
        log.info("event %s already taken, skipped", event_id)
        return
    reply_token = event.get("replyToken")

    try:
        content = api.get_content(message["id"])
    except httpx.HTTPError as exc:
        log.error("event %s: downloading message %s failed: %s", event_id, message["id"], _why(exc))
        if event_id is not None:
            session.get(LineWebhookEvent, event_id).download_failed = True
            session.commit()
        _reply(api, reply_token, download_failed_reply(), event_id)
        return
    if not is_template_file(content):
        log.info("event %s: message %s is not a 範本, no reply", event_id, message["id"])
        return

    source = event.get("source") or {}
    user_id = source.get("userId")
    filename = message.get("fileName") or "line.xlsx"
    try:
        if user_id:
            _remember_uploader(session, api, user_id, source)
        result = process_upload(session, uploader_line_id=user_id, filename=filename, file_bytes=content, now=now)
    except Exception as exc:
        # process_upload handles bad files itself; this failed before it kept the original.
        log.error("event %s: processing failed before the file was kept: %s", event_id, type(exc).__name__)
        upload_id = _keep_original(session, user_id, filename, content, now, exc, event_id)
        if upload_id is not None and event_id is not None:
            session.get(LineWebhookEvent, event_id).upload_id = upload_id
            session.commit()
        _reply(api, reply_token, processing_failed_reply(original_kept=upload_id is not None), event_id)
        return

    if event_id is not None:
        session.get(LineWebhookEvent, event_id).upload_id = result.upload_id
        session.commit()
    log.info("event %s: upload %s processed", event_id, result.upload_id)
    _reply(api, reply_token, result.reply_text, event_id)


def _keep_original(
    session: Session,
    user_id: str | None,
    filename: str,
    content: bytes,
    now: datetime,
    exc: Exception,
    event_id: str | None,
) -> int | None:
    """The failed file kept with its reason, or None when even that failed."""
    try:
        return keep_failed_original(
            session, uploader_line_id=user_id, filename=filename, file_bytes=content, now=now, exc=exc
        )
    except Exception as again:
        session.rollback()
        log.error("event %s: the file could not be kept: %s", event_id, type(again).__name__)
        return None


def _claim(session: Session, event_id: str, now: datetime) -> bool:
    """Record the event as taken; False if it already was (a concurrent copy included)."""
    claimed = session.scalar(
        insert(LineWebhookEvent)
        .values(webhook_event_id=event_id, received_at=now)
        .on_conflict_do_nothing()
        .returning(LineWebhookEvent.webhook_event_id)
    )
    session.commit()
    return claimed is not None


def _remember_uploader(session: Session, api: LineApi, user_id: str, source: Mapping[str, Any]) -> None:
    """Record the 傳檔者 with their LINE display name, so 總部 can tell who to confirm."""
    uploader = session.scalar(select(Uploader).where(Uploader.line_user_id == user_id))
    if uploader is not None and uploader.display_name:
        return
    name = api.display_name(source)
    if uploader is None:
        session.execute(
            insert(Uploader).values(line_user_id=user_id, display_name=name).on_conflict_do_nothing()
        )
    elif name:
        uploader.display_name = name
    session.commit()


def _reply(api: LineApi, reply_token: str | None, text: str, event_id: str | None) -> None:
    if not reply_token:
        log.error("event %s: no reply token, the reply could not be sent", event_id)
        return
    try:
        api.reply_text(reply_token, text)
    except httpx.HTTPError as exc:
        log.error("event %s: reply failed: %s", event_id, _why(exc))


def _why(exc: httpx.HTTPError) -> str:
    """Status code or error type; never the response body."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__
