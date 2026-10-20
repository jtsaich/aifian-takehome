"""process_upload: the single entry point for every upload source.

The 模擬群組上傳 page, the LINE webhook and the demo script all call it, so the
stored data and the reply text are identical whichever way a file arrives.
"""

from __future__ import annotations

import hashlib
import logging
import os
import traceback
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.binding import uploader_notice
from bakery.checks import StoredOrder, order_warnings
from bakery.clock import today_taipei
from bakery.merge import merge_orders
from bakery.models import LineStatus, Order, OrderLine, Product, ProductAlias, Store, Upload, Uploader
from bakery.outcome import Failure, FailureKind, ProcessResult, UploadOutcome
from bakery.parsing import FileRejected, ParsedFile, ProductLookup, ProductRef, parse_upload, sort_findings
from bakery.reply import render_reply

log = logging.getLogger(__name__)


def process_upload(
    session: Session,
    *,
    uploader_line_id: str | None,
    filename: str,
    file_bytes: bytes,
    now: datetime,
    submitted_by_id: int | None = None,
) -> ProcessResult:
    """Keep the original, merge its accepted orders, and return the reply for the 傳檔者.

    Never raises on bad input: an unreadable file, an unknown 門市代碼 or an
    unexpected processing error becomes a failure the reply explains. The
    original is committed before parsing starts, so it survives any of these.
    `uploader_line_id` is None when LINE did not say which account sent the file.
    The 門市綁定 (bakery.binding) is checked here, so every source replies alike.
    `now` must be timezone-aware. `submitted_by_id` is the web account that
    sent the file from the 模擬群組上傳 page; None for LINE.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    uploader = _uploader(session, uploader_line_id) if uploader_line_id else None
    upload = Upload(
        uploader=uploader,
        submitted_by_id=submitted_by_id,
        filename=filename,
        content=file_bytes,
        size_bytes=len(file_bytes),
        sha256=hashlib.sha256(file_bytes).hexdigest(),
        received_at=now,
    )
    session.add(upload)
    session.commit()

    try:
        outcome = _process(session, upload, file_bytes, now)
    except FileRejected as rejected:
        session.rollback()
        outcome = _failed(rejected.failure)
    except Exception as exc:
        session.rollback()
        upload.failure_reason = _failure_reason(exc)
        log.error("processing upload %s failed: %s", upload.id, upload.failure_reason)
        outcome = _failed(Failure(FailureKind.INTERNAL_ERROR))

    reply = render_reply(outcome, report_url=_report_url(upload.id))
    upload.store_code = outcome.store_code
    upload.reply_text = reply.text
    upload.report_text = reply.report
    session.commit()
    return ProcessResult(
        upload_id=upload.id, reply_text=reply.text, report_text=reply.report, outcome=outcome
    )


def _process(session: Session, upload: Upload, file_bytes: bytes, now: datetime) -> UploadOutcome:
    today = today_taipei(now)
    parsed = parse_upload(file_bytes, _product_lookup(session), today)
    store = session.get(Store, parsed.store_code)
    if store is None:
        raise FileRejected(Failure(FailureKind.UNKNOWN_STORE, {"store_code": parsed.store_code}))

    stored = _stored_orders(session, store.code, parsed)
    merged = merge_orders(session, upload=upload, store_code=store.code, orders=parsed.orders)
    # Orders re-sent unchanged are not mentioned again, warnings included.
    unchanged = set(merged.unchanged_order_nos)
    warnings = order_warnings([o for o in parsed.orders if o.order_no not in unchanged], today, stored)
    return UploadOutcome(
        store_code=store.code,
        store_name=store.name,
        order_count=len(parsed.orders),
        line_count=parsed.line_count,
        rejected_rows=parsed.rejected_rows,
        findings=sort_findings([*parsed.findings, *warnings], parsed.sheet_names),
        new_order_nos=merged.new_order_nos,
        unchanged_order_nos=merged.unchanged_order_nos,
        changes=merged.changes,
        uploader_notice=uploader_notice(session, upload.uploader, store),
    )


def _failure_reason(exc: Exception) -> str:
    """The exception type and the innermost place in our code it passed: never its
    message, which can quote cell content (names, phones)."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "bakery" in Path(f.filename).parts]
    if not frames:
        return type(exc).__name__
    where = frames[-1]
    return f"{type(exc).__name__}（{Path(where.filename).name}:{where.lineno} {where.name}）"


def _failed(failure: Failure) -> UploadOutcome:
    return UploadOutcome(store_code=None, store_name=None, order_count=0, line_count=0, failure=failure)


def _uploader(session: Session, line_user_id: str) -> Uploader:
    """The 傳檔者 for this LINE account, recorded on first upload."""
    uploader = session.scalar(select(Uploader).where(Uploader.line_user_id == line_user_id))
    if uploader is None:
        uploader = Uploader(line_user_id=line_user_id)
        session.add(uploader)
    return uploader


def _product_lookup(session: Session) -> ProductLookup:
    products = {p.code: ProductRef(p.code, p.name) for p in session.scalars(select(Product))}
    lookup = {ref.name: ref for ref in products.values()}
    lookup.update({a.alias: products[a.product_code] for a in session.scalars(select(ProductAlias))})
    return lookup


def _stored_orders(session: Session, store_code: str, parsed: ParsedFile) -> list[StoredOrder]:
    """The store's live orders on the file's 取貨日, for the duplicate-phone check."""
    pickups = {o.pickup_on for o in parsed.orders}
    if not pickups:
        return []
    rows = session.execute(
        select(Order.order_no, Order.phone, Order.pickup_on).where(
            Order.store_code == store_code,
            Order.pickup_on.in_(pickups),
            Order.lines.any(OrderLine.status == LineStatus.ACTIVE),
        )
    )
    return [StoredOrder(order_no, phone, pickup_on) for order_no, phone, pickup_on in rows]


def _report_url(upload_id: int) -> str:
    """Absolute when PUBLIC_BASE_URL is set (LINE needs a full link), else a site path."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/uploads/{upload_id}"
