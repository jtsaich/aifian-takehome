"""品項 and 修改截止點 upkeep: 總部人員 add 品項 / 品項別名 and set N (the 老闆 may look);
each 門市's 範本, built from the live 品項 list, to download."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.admin import AdminError, add_alias, add_product, products, set_cutoff_days, settings
from bakery.models import Account, Store
from bakery.template import TEMPLATE_VERSION, build_template
from bakery.web.auth import current_account
from bakery.web.deps import get_now, get_session, templates, xlsx_download
from bakery.xlsx import download_bytes

# Viewing (Area.OPERATIONS) and editing (Area.CONFIRMATIONS) are registered apart.
router = APIRouter()
edit_router = APIRouter()


@router.get("/products", response_class=HTMLResponse)
def show_products(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    return _products_page(request, session)


@router.get("/templates/{store_code}.xlsx")
def download_template(
    store_code: str,
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
) -> Response:
    """The 範本 for one 門市, its 品項 dropdown from the 品項 list as it is now."""
    store = session.get(Store, store_code)
    if store is None:
        raise HTTPException(status_code=404)
    wb = build_template(store, [p.name for p in products(session)])
    return xlsx_download(
        download_bytes(wb, now),
        f"{store.code}_{store.name}_喜餅訂單範本_{TEMPLATE_VERSION}.xlsx",
        f"template-{store.code}-{TEMPLATE_VERSION}.xlsx",
    )


@edit_router.post("/products")
def add(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    account: Annotated[Account, Depends(current_account)],
    kind: Annotated[Literal["product", "alias"], Form()],
    name: Annotated[str, Form()],
    product_code: Annotated[str | None, Form()] = None,
) -> Response:
    """A new 品項 (kind=product), or a 品項別名 for `product_code` (kind=alias)."""
    try:
        if kind == "product":
            add_product(session, name, account=account)
        else:
            add_alias(session, product_code or "", name, account=account)
    except AdminError as error:
        session.rollback()
        return _products_page(request, session, error=str(error), status_code=422)
    return RedirectResponse("/products", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def show_settings(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    return _settings_page(request, session)


@edit_router.post("/settings")
def save_settings(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    account: Annotated[Account, Depends(current_account)],
    cutoff: Annotated[str, Form()],
) -> Response:
    try:
        set_cutoff_days(session, int(cutoff) if cutoff.strip().isdigit() else -1, account=account, now=now)
    except AdminError as error:
        session.rollback()
        return _settings_page(request, session, error=str(error), status_code=422)
    return RedirectResponse("/settings", status_code=303)


def _products_page(request: Request, session: Session, *, error: str | None = None, status_code: int = 200):
    stores = session.scalars(select(Store).order_by(Store.code)).all()
    return templates.TemplateResponse(
        request,
        "products.html",
        {"products": products(session), "stores": stores, "error": error},
        status_code=status_code,
    )


def _settings_page(request: Request, session: Session, *, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request, "settings.html", {"settings": settings(session), "error": error}, status_code=status_code
    )
