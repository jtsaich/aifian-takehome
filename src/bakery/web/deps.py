"""Request-scoped dependencies shared by every route: DB session, clock, templates."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from bakery.clock import TAIPEI
from bakery.web.access import Area, may_open


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


def get_now() -> datetime:
    """The clock; tests override this dependency to pin "now"."""
    return datetime.now(TAIPEI)


def _taipei(value: datetime) -> str:
    return value.astimezone(TAIPEI).strftime("%Y/%m/%d %H:%M")


def _ymd(value) -> str:
    return value.strftime("%Y/%m/%d") if value else ""


def _account_context(request: Request) -> dict:
    """`account` (None until login) and `can(Area.X)` for the nav and pages."""
    account = getattr(request.state, "account", None)
    return {"account": account, "Area": Area, "can": lambda area: may_open(account, area)}


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates", context_processors=[_account_context]
)
templates.env.filters["taipei"] = _taipei
templates.env.filters["ymd"] = _ymd
