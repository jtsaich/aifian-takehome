"""總表 page and its .xlsx."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.master_list import COLUMNS, master_list, master_list_xlsx, status_text
from bakery.models import Store
from bakery.web.deps import date_or_none, get_now, get_session, templates, xlsx_download

router = APIRouter()


@router.get("/orders", response_class=HTMLResponse)
def show(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    store: str = "",
    pickup_on: str = "",
) -> HTMLResponse:
    pickup = date_or_none(pickup_on)
    lines = master_list(session, store_code=store or None, pickup_on=pickup)
    stores = session.scalars(select(Store).order_by(Store.code)).all()
    return templates.TemplateResponse(
        request,
        "master_list.html",
        {
            "lines": lines,
            "stores": stores,
            "store": store,
            "pickup_on": pickup,
            "columns": COLUMNS,
            "status_text": status_text,
        },
    )


@router.get("/orders.xlsx")
def export(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    store: str = "",
    pickup_on: str = "",
) -> Response:
    """The same lines as the page with the same filters."""
    lines = master_list(session, store_code=store or None, pickup_on=date_or_none(pickup_on))
    return xlsx_download(
        master_list_xlsx(lines, now), f"總表_{now:%Y%m%d}.xlsx", f"master-list-{now:%Y%m%d}.xlsx"
    )
