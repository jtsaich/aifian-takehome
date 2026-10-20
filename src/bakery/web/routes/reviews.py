"""待處理: 待確認 changes, confirmed or 退回 by a 總部人員 (the 老闆 may look), and the
上傳 whose processing failed on our side."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from bakery.models import Account
from bakery.reviews import (
    STATUS_LABELS,
    ReviewClosed,
    UnknownReview,
    confirm_review,
    entry_text,
    failed_uploads,
    kinds_text,
    reject_review,
    reviews,
    reviews_xlsx,
    uploader_text,
    why_held,
)
from bakery.web.auth import current_account
from bakery.web.deps import get_now, get_session, templates, xlsx_download

# Viewing (Area.OPERATIONS) and deciding (Area.CONFIRMATIONS) are registered apart.
router = APIRouter()
decide_router = APIRouter()


@router.get("/reviews", response_class=HTMLResponse)
def show(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "reviews.html",
        {
            "reviews": reviews(session),
            "failed": failed_uploads(session),
            "status_labels": STATUS_LABELS,
            "entry_text": entry_text,
            "kinds_text": kinds_text,
            "why_held": why_held,
            "uploader_text": uploader_text,
        },
    )


@router.get("/reviews.xlsx")
def export(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
) -> Response:
    """The same lists as the page."""
    return xlsx_download(
        reviews_xlsx(reviews(session), failed_uploads(session), now),
        f"待處理_{now:%Y%m%d}.xlsx",
        f"reviews-{now:%Y%m%d}.xlsx",
    )


@decide_router.post("/reviews")
def decide(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    account: Annotated[Account, Depends(current_account)],
    review_id: Annotated[int, Form()],
    decision: Annotated[Literal["confirm", "reject"], Form()],
) -> RedirectResponse:
    act = confirm_review if decision == "confirm" else reject_review
    try:
        act(session, review_id=review_id, account=account, now=now)
    except UnknownReview:
        raise HTTPException(status_code=404) from None
    except ReviewClosed:
        raise HTTPException(status_code=409, detail="這筆待確認已經處理過了") from None
    return RedirectResponse("/reviews", status_code=303)
