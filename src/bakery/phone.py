"""Taiwan phone numbers as stores type them: 0912-345-678, 0912 345 678, +886 912 345 678, 04-2345-6789."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

_SEPARATORS = re.compile(r"[\s\-().]")


class PhoneProblem(StrEnum):
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    MALFORMED = "malformed"


def phone_digits(text: str) -> str | None:
    """Digits in domestic form (leading 0), or None if anything but digits and separators is in it."""
    compact = _SEPARATORS.sub("", unicodedata.normalize("NFKC", text))
    if compact.startswith("+886"):
        compact = "0" + compact[4:].removeprefix("0")
    if not compact.isdigit():
        return None
    return compact


def phone_problem(text: str) -> PhoneProblem | None:
    """None when `text` is a plausible mobile (09 + 8 digits) or landline (0[2-8], 9-10 digits)."""
    digits = phone_digits(text)
    if digits is None or not digits.startswith("0") or digits.startswith("00"):
        return PhoneProblem.MALFORMED
    expected = (10, 10) if digits.startswith("09") else (9, 10)
    if len(digits) < expected[0]:
        return PhoneProblem.TOO_SHORT
    if len(digits) > expected[1]:
        return PhoneProblem.TOO_LONG
    return None
