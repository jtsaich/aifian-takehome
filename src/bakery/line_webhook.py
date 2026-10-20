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
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bakery.line import LineApi
from bakery.models import LineWebhookEvent, Upload, Uploader
from bakery.parsing import is_template_file
from bakery.pipeline import process_upload
from bakery.reply import PROCESSING_FAILED

log = logging.getLogger(__name__)

_FILENAME_MAX = Upload.__table__.c.filename.type.length


def handle_events(session: Session, api: LineApi, events: Iterable[Mapping[str, Any]], now: datetime) -> bool:
    """Handle every file message. False if one should come again: its file could not be
    downloaded, so the event was released for LINE to redeliver."""
    ok = True
    for event in events:
        message = event.get("message") or {}
        if event.get("type") == "message" and message.get("type") == "file":
            ok = _handle_file(session, api, event, message, now) and ok
    return ok


def _handle_file(
    session: Session, api: LineApi, event: Mapping[str, Any], message: Mapping[str, Any], now: datetime
) -> bool:
    event_id = event.get("webhookEventId")
    if event_id is not None and not _claim(session, event_id, now):
        log.info("event %s already taken, skipped", event_id)
        return True

    try:
        content = api.get_content(message["id"])
    except httpx.HTTPError as exc:
        log.error("event %s: downloading message %s failed: %s", event_id, message["id"], _why(exc))
        if event_id is not None:
            _release(session, event_id)
        return False
    if not is_template_file(content):
        log.info("event %s: message %s is not a 範本, no reply", event_id, message["id"])
        return True

    source = event.get("source") or {}
    user_id = source.get("userId")
    reply_token = event.get("replyToken")
    try:
        if user_id:
            _remember_uploader(session, api, user_id, source)
        result = process_upload(
            session,
            uploader_line_id=user_id,
            filename=(message.get("fileName") or "line.xlsx")[:_FILENAME_MAX],
            file_bytes=content,
            now=now,
        )
    except Exception as exc:
        # process_upload handles bad files itself; this is the database or the like failing.
        session.rollback()
        log.error("event %s: the file could not be kept: %s", event_id, type(exc).__name__)
        _reply(api, reply_token, PROCESSING_FAILED, event_id)
        return True

    if event_id is not None:
        session.get(LineWebhookEvent, event_id).upload_id = result.upload_id
        session.commit()
    log.info("event %s: upload %s processed", event_id, result.upload_id)
    _reply(api, reply_token, result.reply_text, event_id)
    return True


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


def _release(session: Session, event_id: str) -> None:
    session.execute(delete(LineWebhookEvent).where(LineWebhookEvent.webhook_event_id == event_id))
    session.commit()


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
