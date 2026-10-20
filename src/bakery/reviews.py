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

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from bakery.changes import apply_diffs
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
    """Every 待確認 still waiting (oldest first), then decided ones (latest decision first)."""
    return list(
        session.scalars(
            select(PendingReview)
            .where(PendingReview.status != ReviewStatus.SUPERSEDED)
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
                PendingReview.decided_at.desc(),
                PendingReview.id,
            )
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
