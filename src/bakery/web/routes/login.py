"""登入 / 登出. Public by design: registered without `requires`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from bakery.accounts import authenticate
from bakery.web.auth import log_in, log_out
from bakery.web.deps import get_session, templates

router = APIRouter()


def _local_path(next_url: str) -> str:
    """Only same-site paths, so the login form can't bounce someone to another site."""
    if next_url.startswith("/") and not next_url.startswith(("//", "/\\")):
        return next_url
    return "/"


@router.get("/login", response_class=HTMLResponse)
def show(request: Request, next: str = "/") -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"next": _local_path(next)})


@router.post("/login", response_model=None)
def submit(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> HTMLResponse | RedirectResponse:
    account = authenticate(session, username, password)
    if account is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": _local_path(next), "username": username, "error": "帳號或密碼錯誤"},
            status_code=401,
        )
    log_in(request, account)
    return RedirectResponse(_local_path(next), status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    log_out(request)
    return RedirectResponse("/login", status_code=303)
