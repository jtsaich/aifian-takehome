"""All "today" / cut-off logic runs on Asia/Taipei time."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def today_taipei(now: datetime | None = None) -> date:
    """Calendar date in Taipei for `now` (an aware datetime; defaults to the real clock)."""
    return (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date()


def taipei_text(value: datetime) -> str:
    """「2026/10/21 14:05」: a moment as pages and downloads show it, in Taipei time."""
    return value.astimezone(TAIPEI).strftime("%Y/%m/%d %H:%M")


def date_text(d: date) -> str:
    """「2026/11/08」: a date as replies and pages write it."""
    return f"{d.year}/{d.month:02d}/{d.day:02d}"
