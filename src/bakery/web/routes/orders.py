"""稽核頁: one 喜餅訂單 as it is now, with every 上傳 that brought it in or changed it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from bakery.models import Change, ChangeEntry, Order, OrderLine, PendingReview, Upload
from bakery.web.deps import get_session, templates

router = APIRouter()


@router.get("/orders/{order_id}", response_class=HTMLResponse, name="order_detail")
def detail(
    order_id: int, request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    order = session.get(
        Order,
        order_id,
        options=[joinedload(Order.store), selectinload(Order.lines).joinedload(OrderLine.product)],
    )
    if order is None:
        raise HTTPException(status_code=404)
    changes = session.scalars(
        select(Change)
        .where(Change.order_id == order.id)
        .options(
            joinedload(Change.upload).joinedload(Upload.uploader),
            joinedload(Change.upload).joinedload(Upload.submitted_by),
            selectinload(Change.entries).joinedload(ChangeEntry.product),
            joinedload(Change.review).joinedload(PendingReview.decided_by),
        )
        .order_by(Change.id)
    ).all()
    return templates.TemplateResponse(request, "order_detail.html", {"order": order, "changes": changes})
