"""待處理: 待確認 changes, confirmed or 退回 by a 總部人員 (the 老闆 may look)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from bakery.models import Account
from bakery.reviews import ReviewClosed, UnknownReview, confirm_review, reject_review, reviews
from bakery.web.auth import current_account
from bakery.web.deps import get_now, get_session, templates

# Viewing (Area.OPERATIONS) and deciding (Area.CONFIRMATIONS) are registered apart.
router = APIRouter()
decide_router = APIRouter()


@router.get("/reviews", response_class=HTMLResponse)
def show(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    return templates.TemplateResponse(request, "reviews.html", {"reviews": reviews(session)})


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
