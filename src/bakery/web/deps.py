"""Request-scoped dependencies shared by every route: DB session, clock, templates."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from bakery.clock import TAIPEI


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


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["taipei"] = _taipei
templates.env.filters["ymd"] = _ymd
