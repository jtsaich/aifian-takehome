"""總表 page."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.master_list import master_list
from bakery.models import Store
from bakery.web.deps import get_session, templates

router = APIRouter()


def _date_or_none(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


@router.get("/orders", response_class=HTMLResponse)
def show(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    store: str = "",
    pickup_on: str = "",
) -> HTMLResponse:
    pickup = _date_or_none(pickup_on)
    lines = master_list(session, store_code=store or None, pickup_on=pickup)
    stores = session.scalars(select(Store).order_by(Store.code)).all()
    return templates.TemplateResponse(
        request,
        "master_list.html",
        {"lines": lines, "stores": stores, "store": store, "pickup_on": pickup},
    )
