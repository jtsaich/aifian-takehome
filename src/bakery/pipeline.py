"""process_upload: the single entry point for every upload source.

The 模擬群組上傳 page, the LINE webhook and the demo script all call it, so the
stored data and the reply text are identical whichever way a file arrives.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.merge import merge_orders
from bakery.models import Product, ProductAlias, Store, Upload, Uploader
from bakery.outcome import ProcessResult, UploadOutcome
from bakery.parsing import ProductLookup, parse_upload
from bakery.reply import render_reply


def process_upload(
    session: Session,
    *,
    uploader_line_id: str,
    filename: str,
    file_bytes: bytes,
    now: datetime,
    submitted_by_id: int | None = None,
) -> ProcessResult:
    """Keep the original, merge its orders, and return the reply for the 傳檔者.

    The original is committed before parsing starts, so it survives a failure
    further down. `now` must be timezone-aware. `submitted_by_id` is the web
    account that sent the file from the 模擬群組上傳 page; None for LINE.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    upload = Upload(
        uploader=_uploader(session, uploader_line_id),
        submitted_by_id=submitted_by_id,
        filename=filename,
        content=file_bytes,
        size_bytes=len(file_bytes),
        sha256=hashlib.sha256(file_bytes).hexdigest(),
        received_at=now,
    )
    session.add(upload)
    session.commit()

    parsed = parse_upload(file_bytes, _product_lookup(session))
    store = session.get_one(Store, parsed.store_code)
    merge_orders(session, store_code=store.code, orders=parsed.orders)

    outcome = UploadOutcome(
        store_code=store.code,
        store_name=store.name,
        order_count=len(parsed.orders),
        line_count=parsed.line_count,
    )
    reply_text = render_reply(outcome)
    upload.store_code = store.code
    upload.reply_text = reply_text
    session.commit()
    return ProcessResult(upload_id=upload.id, reply_text=reply_text, outcome=outcome)


def _uploader(session: Session, line_user_id: str) -> Uploader:
    """The 傳檔者 for this LINE account, recorded on first upload."""
    uploader = session.scalar(select(Uploader).where(Uploader.line_user_id == line_user_id))
    if uploader is None:
        uploader = Uploader(line_user_id=line_user_id)
        session.add(uploader)
    return uploader


def _product_lookup(session: Session) -> ProductLookup:
    lookup = {p.name: p.code for p in session.scalars(select(Product))}
    lookup.update({a.alias: a.product_code for a in session.scalars(select(ProductAlias))})
    return lookup
