"""門市綁定: 總部 sees which 門市 each 傳檔者 was recorded for and confirms (or corrects) it."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.binding import UnknownBinding, bindings, confirm_binding
from bakery.models import Account, Store
from bakery.web.auth import current_account
from bakery.web.deps import get_now, get_session, templates

# Viewing (Area.OPERATIONS) and confirming (Area.CONFIRMATIONS) are registered apart.
router = APIRouter()
confirm_router = APIRouter()


@router.get("/bindings", response_class=HTMLResponse)
def show(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    stores = session.scalars(select(Store).order_by(Store.code)).all()
    return templates.TemplateResponse(
        request, "bindings.html", {"bindings": bindings(session), "stores": stores}
    )


@confirm_router.post("/bindings")
def confirm(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    account: Annotated[Account, Depends(current_account)],
    uploader_id: Annotated[int, Form()],
    store_code: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        confirm_binding(session, uploader_id=uploader_id, store_code=store_code, account=account, now=now)
    except UnknownBinding:
        raise HTTPException(status_code=404) from None
    return RedirectResponse("/bindings", status_code=303)
