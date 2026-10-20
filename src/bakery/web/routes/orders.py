"""稽核頁: one 喜餅訂單 as it is now, with every 上傳 that brought it in or changed it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from bakery.changes import DATE_FIELDS, FIELD_LABELS, KIND_LABELS
from bakery.models import Change, ChangeEntry, ChangeField, LineStatus, Order, OrderLine, Upload
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
        )
        .order_by(Change.id)
    ).all()
    return templates.TemplateResponse(
        request,
        "order_detail.html",
        {
            "order": order,
            "changes": changes,
            "kind_labels": KIND_LABELS,
            "field_labels": FIELD_LABELS,
            "show_value": _show_value,
        },
    )


def _show_value(field: ChangeField, text: str | None) -> str:
    """A logged value as the page shows it."""
    if text is None:
        return ""
    if field in DATE_FIELDS:
        return text.replace("-", "/")
    if field is ChangeField.STATUS:
        return "取消" if text == LineStatus.CANCELLED else "（空白）"
    return text
