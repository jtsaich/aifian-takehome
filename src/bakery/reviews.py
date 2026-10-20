"""待確認: held changes that wait for a 總部人員 to confirm or 退回 (reject).

A change becomes 待確認 when bakery.changes.decide holds it (past the 修改截止點, or a
suspected reused 單號). Confirming applies the held change to the order; 退回 leaves
the order as it was. Either way the 門市 hears it at the top of its next upload's
reply (no push). The held Change stays in the append-only change log untouched; its
fate is the PendingReview.

A 門市 that sends the held content again doesn't create another 待確認: it gets a
reminder (still waiting / already 退回). Sending the order back as it is on record
ends the reminder; any other content is a new 修改 and supersedes a pending one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from openpyxl import Workbook
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from bakery.changes import FIELD_LABELS, KIND_LABELS, apply_diffs, is_suspected_reuse, show_value
from bakery.clock import taipei_text
from bakery.models import (
    Account,
    Change,
    ChangeEntry,
    Order,
    PendingReview,
    ReviewStatus,
    Upload,
)
from bakery.outcome import FieldDiff, HeldChange
from bakery.xlsx import download_bytes, finish_sheet

# A held change the 門市 can still be reminded of when it sends the same content again.
_OPEN = (ReviewStatus.PENDING, ReviewStatus.REJECTED)


def open_reviews(session: Session, order_ids: Iterable[int]) -> dict[int, PendingReview]:
    """By order id: the 待確認 (pending or 退回) from the order's latest change, if any.

    Only the latest change counts: once the 門市 sent other content that was logged,
    an older 待確認 is history, not something to remind them of.
    """
    latest = (
        select(func.max(Change.id))
        .where(Change.order_id.in_(list(order_ids)))
        .group_by(Change.order_id)
        .scalar_subquery()
    )
    reviews = session.scalars(
        select(PendingReview)
        .where(PendingReview.change_id.in_(latest), PendingReview.status.in_(_OPEN))
        .options(joinedload(PendingReview.change).selectinload(Change.entries))
        .execution_options(populate_existing=True)  # decided in another session meanwhile
    )
    return {r.change.order_id: r for r in reviews}


def same_content(review: PendingReview, diffs: Sequence[FieldDiff]) -> bool:
    """Whether `diffs` (a file against the order on record) are exactly the held change."""
    held = {(e.field, e.product_code, e.old_value, e.new_value) for e in review.change.entries}
    return held == {(d.field, d.product_code, d.old, d.new) for d in diffs}


def supersede(review: PendingReview) -> None:
    """The 門市 sent other content for the order before 總部 decided: nothing to decide."""
    if review.status == ReviewStatus.PENDING:
        review.status = ReviewStatus.SUPERSEDED


def reviews(session: Session) -> list[PendingReview]:
    """Every 待確認 still waiting (oldest first), then the rest, decided or superseded
    (latest decision first, superseded ones after them, newest first)."""
    return list(
        session.scalars(
            select(PendingReview)
            .options(
                joinedload(PendingReview.decided_by),
                joinedload(PendingReview.change).joinedload(Change.order).joinedload(Order.store),
                joinedload(PendingReview.change).joinedload(Change.upload).joinedload(Upload.uploader),
                joinedload(PendingReview.change)
                .selectinload(Change.entries)
                .joinedload(ChangeEntry.product),
            )
            .order_by(
                (PendingReview.status != ReviewStatus.PENDING),
                PendingReview.decided_at.desc().nulls_last(),
                case((PendingReview.status == ReviewStatus.PENDING, PendingReview.id), else_=-PendingReview.id),
            )
        )
    )


def failed_uploads(session: Session) -> list[Upload]:
    """上傳 whose processing broke on our side (failure_reason set), newest first: the
    reply told the 門市 that 總部 was notified, and this is where 總部 sees them."""
    return list(
        session.scalars(
            select(Upload)
            .where(Upload.failure_reason.is_not(None))
            .options(joinedload(Upload.uploader))
            .order_by(Upload.received_at.desc(), Upload.id.desc())
        )
    )


class UnknownReview(LookupError):
    pass


class ReviewClosed(Exception):
    """Already decided (or superseded): another 總部人員 got there first."""


def confirm_review(session: Session, *, review_id: int, account: Account, now: datetime) -> PendingReview:
    """Apply the held change to the order: from now on it counts, in production too."""
    review = _pending(session, review_id)
    order = session.get(Order, review.change.order_id, options=[selectinload(Order.lines)])
    apply_diffs(order, _diffs(review.change.entries))
    return _decided(session, review, ReviewStatus.CONFIRMED, account, now)


def reject_review(session: Session, *, review_id: int, account: Account, now: datetime) -> PendingReview:
    """退回: the order keeps its content from before the change."""
    return _decided(session, _pending(session, review_id), ReviewStatus.REJECTED, account, now)


def report_decisions(session: Session, *, upload: Upload, store_code: str) -> tuple[HeldChange, ...]:
    """總部's decisions on `store_code`'s 待確認 not yet told: this upload's reply tells them."""
    decided = session.scalars(
        select(PendingReview)
        .join(PendingReview.change)
        .join(Change.order)
        .where(
            Order.store_code == store_code,
            PendingReview.status.in_((ReviewStatus.CONFIRMED, ReviewStatus.REJECTED)),
            PendingReview.reported_upload_id.is_(None),
        )
        .options(
            joinedload(PendingReview.change).joinedload(Change.order),
            joinedload(PendingReview.change).selectinload(Change.entries).joinedload(ChangeEntry.product),
        )
        .order_by(PendingReview.decided_at, PendingReview.id)
        .execution_options(populate_existing=True)
    ).all()
    for review in decided:
        review.reported_upload = upload
    return tuple(held_change(r) for r in decided)


def held_change(review: PendingReview) -> HeldChange:
    change = review.change
    return HeldChange(change.order.order_no, change.change_kinds, _diffs(change.entries), review.status)


def _diffs(entries: Iterable[ChangeEntry]) -> tuple[FieldDiff, ...]:
    return tuple(
        FieldDiff(
            e.field,
            e.old_value,
            e.new_value,
            product_code=e.product_code,
            product_name=e.product.name if e.product else None,
        )
        for e in entries
    )


def _pending(session: Session, review_id: int) -> PendingReview:
    # Locked: two 總部人員 deciding at once, the second one sees it closed.
    review = session.get(PendingReview, review_id, with_for_update=True)
    if review is None:
        raise UnknownReview(review_id)
    if review.status != ReviewStatus.PENDING:
        raise ReviewClosed(review_id)
    return review


def _decided(
    session: Session, review: PendingReview, status: ReviewStatus, account: Account, now: datetime
) -> PendingReview:
    review.status = status
    review.decided_by = account
    review.decided_at = now
    session.commit()
    return review


STATUS_LABELS: dict[ReviewStatus, str] = {
    ReviewStatus.PENDING: "待確認",
    ReviewStatus.CONFIRMED: "已確認",
    ReviewStatus.REJECTED: "已退回",
    ReviewStatus.SUPERSEDED: "被取代",
}
REVIEW_COLUMNS = ("狀態", "門市", "單號", "修改類型", "舊值 → 新值", "上傳", "上傳時間", "處理人", "處理時間")
FAILED_COLUMNS = ("上傳", "收到時間", "檔名", "傳檔者", "失敗原因")


def why_held(change: Change) -> str:
    if is_suspected_reuse(change.change_kinds):
        return "疑似單號重複使用，不看截止點"
    return "已過修改截止點"


def kinds_text(change: Change) -> str:
    return "＋".join(KIND_LABELS[k] for k in change.change_kinds)


def entry_text(e: ChangeEntry) -> str:
    """「盒數（龍鳳喜餅）：80 → 120」, as the 待處理 page and its .xlsx list it."""
    product = f"（{e.product.name}）" if e.product else ""
    old = show_value(e.field, e.old_value) or "空白"
    new = show_value(e.field, e.new_value) or "空白"
    return f"{FIELD_LABELS[e.field]}{product}：{old} → {new}"


def uploader_text(upload: Upload) -> str:
    if upload.uploader is None:
        return ""
    return upload.uploader.display_name or upload.uploader.line_user_id


def reviews_xlsx(all_reviews: Sequence[PendingReview], failed: Sequence[Upload], now: datetime) -> bytes:
    """The 待處理 page as a workbook: every 待確認 in the page's order, and the failed 上傳."""
    wb = Workbook()
    ws = wb.active
    ws.title = "待處理"
    ws.append(REVIEW_COLUMNS)
    for r in all_reviews:
        change, upload = r.change, r.change.upload
        ws.append(
            (
                STATUS_LABELS[r.status],
                f"{change.order.store.name}（{change.order.store_code}）",
                change.order.order_no,
                kinds_text(change),
                "\n".join(entry_text(e) for e in change.entries),
                f"上傳 #{upload.id}",
                taipei_text(upload.received_at),
                r.decided_by.display_name if r.decided_by else None,
                taipei_text(r.decided_at) if r.decided_at else None,
            )
        )
    finish_sheet(ws)
    failures = wb.create_sheet("處理失敗的檔案")
    failures.append(FAILED_COLUMNS)
    for u in failed:
        failures.append((f"上傳 #{u.id}", taipei_text(u.received_at), u.filename, uploader_text(u), u.failure_reason))
    finish_sheet(failures)
    return download_bytes(wb, now)
