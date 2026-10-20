"""process_upload: the single entry point for every upload source.

The 模擬群組上傳 page, the LINE webhook and the demo script all call it, so the
stored data and the reply text are identical whichever way a file arrives.
"""

from __future__ import annotations

import hashlib
import logging
import traceback
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.binding import uploader_notice
from bakery.checks import StoredOrder, order_warnings
from bakery.clock import today_taipei
from bakery.merge import merge_orders
from bakery.models import LineStatus, Order, OrderLine, Product, ProductAlias, Store, Upload, Uploader
from bakery.outcome import Failure, FailureKind, Finding, FindingKind, ProcessResult, Severity, UploadOutcome
from bakery.parsing import (
    FileRejected,
    ParsedFile,
    ProductLookup,
    ProductRef,
    group_rows,
    parse_upload,
    sort_findings,
)
from bakery.reply import render_reply, site_url

log = logging.getLogger(__name__)


def process_upload(
    session: Session,
    *,
    uploader_line_id: str | None,
    filename: str,
    file_bytes: bytes,
    now: datetime,
    submitted_by_id: int | None = None,
    historical: bool = False,
) -> ProcessResult:
    """Keep the original, merge its accepted orders, and return the reply for the 傳檔者.

    Never raises on bad input: an unreadable file, an unknown 門市代碼 or an
    unexpected processing error becomes a failure the reply explains. The
    original is committed before parsing starts, so it survives any of these.
    `uploader_line_id` is None when LINE did not say which account sent the file.
    The 門市綁定 (bakery.binding) is checked here, so every source replies alike.
    `now` must be timezone-aware. `submitted_by_id` is the web account that
    sent the file from the 模擬群組上傳 or 歷史資料匯入 page; None for LINE.

    `historical` is a 歷史資料匯入 by a 總部人員 (no 傳檔者, so no uploader_line_id):
    its orders are flagged is_historical, no change is held for 總部, 取貨日 warnings
    are left out (the dates are past by design), an order received after go-live is
    never overwritten, and nobody is replied to: reply_text is None, the report is
    for the import page.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if historical and uploader_line_id is not None:
        raise ValueError("a 歷史資料匯入 has no 傳檔者")
    uploader = _uploader(session, uploader_line_id) if uploader_line_id else None
    upload = Upload(
        uploader=uploader,
        submitted_by_id=submitted_by_id,
        is_historical=historical,
        filename=filename,
        content=file_bytes,
        size_bytes=len(file_bytes),
        sha256=hashlib.sha256(file_bytes).hexdigest(),
        received_at=now,
    )
    session.add(upload)
    session.commit()

    try:
        outcome = _process(session, upload, file_bytes, now, historical=historical)
    except FileRejected as rejected:
        session.rollback()
        outcome = _failed(rejected.failure)
    except Exception as exc:
        session.rollback()
        upload.failure_reason = _failure_reason(exc)
        log.error("processing upload %s failed: %s", upload.id, upload.failure_reason)
        outcome = _failed(Failure(FailureKind.INTERNAL_ERROR))

    reply = render_reply(outcome, report_url=site_url(f"/uploads/{upload.id}"))
    reply_text = None if historical else reply.text
    upload.store_code = outcome.store_code
    upload.reply_text = reply_text
    upload.report_text = reply.report
    session.commit()
    return ProcessResult(
        upload_id=upload.id, reply_text=reply_text, report_text=reply.report, outcome=outcome
    )


# 歷史資料's 取貨日 are in the past by design: warning about them would be noise.
_PICKUP_WARNINGS = frozenset({FindingKind.PICKUP_IN_PAST, FindingKind.PICKUP_TOO_SOON})


def _process(
    session: Session, upload: Upload, file_bytes: bytes, now: datetime, *, historical: bool
) -> UploadOutcome:
    today = today_taipei(now)
    parsed = parse_upload(file_bytes, _product_lookup(session), today)
    store = session.get(Store, parsed.store_code)
    if store is None:
        raise FileRejected(Failure(FailureKind.UNKNOWN_STORE, {"store_code": parsed.store_code}))

    if historical:
        parsed = _without_live_orders(session, store.code, parsed)
    stored = _stored_orders(session, store.code, parsed)
    merged = merge_orders(
        session, upload=upload, store_code=store.code, orders=parsed.orders, historical=historical
    )
    # Orders re-sent unchanged are not mentioned again, warnings included.
    unchanged = set(merged.unchanged_order_nos)
    warnings = order_warnings([o for o in parsed.orders if o.order_no not in unchanged], today, stored)
    if historical:
        warnings = [w for w in warnings if w.kind not in _PICKUP_WARNINGS]
    return UploadOutcome(
        store_code=store.code,
        store_name=store.name,
        order_count=len(parsed.orders),
        line_count=parsed.line_count,
        rejected_rows=parsed.rejected_rows,
        findings=sort_findings([*parsed.findings, *warnings], parsed.sheet_names),
        uploader_notice=None if historical else uploader_notice(session, upload.uploader, store),
        new_order_nos=merged.new_order_nos,
        unchanged_order_nos=merged.unchanged_order_nos,
        changes=merged.changes,
    )


def _without_live_orders(session: Session, store_code: str, parsed: ParsedFile) -> ParsedFile:
    """`parsed` minus orders whose 單號 the 門市 already sent after go-live: 歷史資料 never
    overwrites those. Each one becomes an error and its rows count as not taken in."""
    live = set(
        session.scalars(
            select(Order.order_no).where(
                Order.store_code == store_code,
                Order.order_no.in_([o.order_no for o in parsed.orders]),
                Order.is_historical.is_(False),
            )
        )
    )
    if not live:
        return parsed
    refused = [o for o in parsed.orders if o.order_no in live]
    errors = [Finding(FindingKind.LIVE_ORDER_NO, Severity.ERROR, o.locations, (o.order_no,)) for o in refused]
    position = {name: i for i, name in enumerate(parsed.sheet_names)}
    rejected = {(loc.sheet, r) for loc in parsed.rejected_rows for r in loc.rows}
    rejected |= {(line.sheet, line.row) for o in refused for line in o.lines}
    return replace(
        parsed,
        orders=tuple(o for o in parsed.orders if o.order_no not in live),
        findings=sort_findings([*parsed.findings, *errors], parsed.sheet_names),
        rejected_rows=group_rows(sorted(rejected, key=lambda sr: (position[sr[0]], sr[1]))),
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
