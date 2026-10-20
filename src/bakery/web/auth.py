"""Login state: the signed session cookie and the dependencies that guard pages.

Pages are guarded per router at registration (`bakery.web.app`), never by a
global middleware, so routes that authenticate differently (the LINE webhook
verifies LINE's signature) are simply registered without `requires`.
"""

from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.params import Depends as DependsParam
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from bakery.models import Account
from bakery.web.access import Area, may_open
from bakery.web.deps import get_session, templates

DEV_SESSION_SECRET = "dev-only-session-secret-do-not-deploy"
SESSION_COOKIE = "bakery_session"
SESSION_MAX_AGE = 12 * 60 * 60  # one working day; then log in again
_ACCOUNT_KEY = "account_id"


def is_production() -> bool:
    return os.environ.get("BAKERY_ENV") == "production"


def session_secret() -> str:
    """SESSION_SECRET, or a dev default that production refuses to run with."""
    secret = os.environ.get("SESSION_SECRET", "")
    if is_production() and (secret == DEV_SESSION_SECRET or len(secret) < 32):
        raise RuntimeError("BAKERY_ENV=production needs SESSION_SECRET set to 32+ random characters")
    return secret or DEV_SESSION_SECRET


def install(app: FastAPI) -> None:
    """Session cookie plus the handlers that turn a refused request into a page."""
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret(),
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=is_production(),
    )
    app.add_exception_handler(LoginRequired, _to_login)
    app.add_exception_handler(Forbidden, _forbidden)


def log_in(request: Request, account: Account) -> None:
    request.session.clear()
    request.session[_ACCOUNT_KEY] = account.id


def log_out(request: Request) -> None:
    request.session.clear()


class LoginRequired(Exception):
    """No valid session: send the visitor to the login page."""


class Forbidden(Exception):
    """Logged in, but this account's role may not open the page."""


def current_account(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> Account:
    """The logged-in account; every write records it. Raises LoginRequired if none."""
    account_id = request.session.get(_ACCOUNT_KEY)
    account = session.get(Account, account_id) if isinstance(account_id, int) else None
    if account is None:
        raise LoginRequired
    request.state.account = account  # for the nav in base.html
    return account


def requires(area: Area) -> DependsParam:
    """Router dependency: only roles the access matrix allows into `area` get through."""

    def check(account: Annotated[Account, Depends(current_account)]) -> None:
        if not may_open(account, area):
            raise Forbidden

    return Depends(check)


def _to_login(request: Request, exc: Exception) -> RedirectResponse:
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)


def _forbidden(request: Request, exc: Exception) -> HTMLResponse:
    return templates.TemplateResponse(request, "forbidden.html", status_code=403)
