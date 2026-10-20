"""客人資料: internal order history per 客人 (one normalized phone), and its .xlsx export.

Read-only by design: 客人資料 is never used to send messages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from bakery.customers import customer_of_order, customer_records, customer_records_xlsx
from bakery.web.deps import get_now, get_session, templates, xlsx_download

router = APIRouter()


@router.get("/customers", response_class=HTMLResponse)
def index(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "customers.html", {"records": customer_records(session)}
    )


@router.get("/customers.xlsx")
def export(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
) -> Response:
    return xlsx_download(
        customer_records_xlsx(customer_records(session), now),
        f"客人資料_{now:%Y%m%d}.xlsx",
        f"customers-{now:%Y%m%d}.xlsx",
    )


@router.get("/customers/{order_id}", response_class=HTMLResponse)
def detail(
    order_id: int, request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    """The 客人 who placed order `order_id` (any of their orders works)."""
    customer = customer_of_order(session, order_id)
    if customer is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "customer_detail.html", {"customer": customer})
