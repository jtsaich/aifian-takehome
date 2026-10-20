"""All "today" / cut-off logic runs on Asia/Taipei time."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def today_taipei(now: datetime | None = None) -> date:
    """Calendar date in Taipei for `now` (an aware datetime; defaults to the real clock)."""
    return (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date()
