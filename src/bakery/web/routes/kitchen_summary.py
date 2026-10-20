"""廚房彙總 page and its .xlsx, for a range of 取貨日 (default: DEFAULT_DAYS from today)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from bakery.clock import today_taipei
from bakery.kitchen_summary import (
    DEFAULT_DAYS,
    PENDING,
    PENDING_COLUMNS,
    date_range,
    kitchen_summary,
    kitchen_summary_xlsx,
    weekday,
)
from bakery.reply import KITCHEN_SUMMARY_PATH
from bakery.web.deps import date_or_none, get_now, get_session, templates, xlsx_download

router = APIRouter()


def _range(now: datetime, start: str, end: str) -> tuple[date, date]:
    return date_range(today_taipei(now), date_or_none(start), date_or_none(end))


@router.get(KITCHEN_SUMMARY_PATH, response_class=HTMLResponse)
def show(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    start: str = "",
    end: str = "",
) -> HTMLResponse:
    summary = kitchen_summary(session, *_range(now, start, end))
    return templates.TemplateResponse(
        request,
        "kitchen_summary.html",
        {
            "summary": summary,
            "weekday": weekday,
            "pending_label": PENDING,
            "pending_columns": PENDING_COLUMNS,
            "default_days": DEFAULT_DAYS,
        },
    )


@router.get(f"{KITCHEN_SUMMARY_PATH}.xlsx")
def export(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    start: str = "",
    end: str = "",
) -> Response:
    """The page for the same range, as a workbook."""
    summary = kitchen_summary(session, *_range(now, start, end))
    span = f"{summary.start:%Y%m%d}-{summary.end:%Y%m%d}"
    return xlsx_download(
        kitchen_summary_xlsx(summary, now), f"廚房彙總_{span}.xlsx", f"kitchen-summary-{span}.xlsx"
    )
