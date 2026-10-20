"""品項 and 修改截止點 upkeep: 總部人員 add 品項 / 品項別名 and set N (the 老闆 may look)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from bakery.admin import AdminError, add_alias, add_product, cutoff_days, products, set_cutoff_days
from bakery.web.deps import get_session, templates

# Viewing (Area.OPERATIONS) and editing (Area.CONFIRMATIONS) are registered apart.
router = APIRouter()
edit_router = APIRouter()


@router.get("/products", response_class=HTMLResponse)
def show_products(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    return _products_page(request, session)


@edit_router.post("/products")
def add(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    kind: Annotated[Literal["product", "alias"], Form()],
    name: Annotated[str, Form()],
    product_code: Annotated[str | None, Form()] = None,
) -> Response:
    """A new 品項 (kind=product), or a 品項別名 for `product_code` (kind=alias)."""
    try:
        if kind == "product":
            add_product(session, name)
        else:
            add_alias(session, product_code or "", name)
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
    cutoff: Annotated[str, Form()],
) -> Response:
    try:
        set_cutoff_days(session, int(cutoff) if cutoff.strip().isdigit() else -1)
    except AdminError as error:
        session.rollback()
        return _settings_page(request, session, error=str(error), status_code=422)
    return RedirectResponse("/settings", status_code=303)


def _products_page(request: Request, session: Session, *, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request, "products.html", {"products": products(session), "error": error}, status_code=status_code
    )


def _settings_page(request: Request, session: Session, *, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"cutoff_days": cutoff_days(session), "error": error},
        status_code=status_code,
    )
