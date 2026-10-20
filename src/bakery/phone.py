"""Taiwan phone numbers as stores type them: 0912-345-678, 0912 345 678, +886 912 345 678, 04-2345-6789.

`normalize_phone` is the one definition of "the same phone": the duplicate-phone
check and 客人資料 both key on it, and `phone_problem` says why a phone has no
normalized form (the 傳檔者 is warned about it).
"""

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
    """Digits in domestic form (leading 0), or None if anything but digits and separators is in it.

    Not yet checked for length; use `normalize_phone` to decide whether two phones are the same.
    """
    compact = _SEPARATORS.sub("", unicodedata.normalize("NFKC", text))
    if compact.startswith("+886"):
        compact = "0" + compact[4:].removeprefix("0")
    if not compact.isdigit():
        return None
    if len(compact) == 9 and compact.startswith("9"):
        # A mobile typed into a number cell: Excel drops the leading 0.
        compact = "0" + compact
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


def normalize_phone(text: str) -> str | None:
    """The phone as bare domestic digits (0912345678, 0423456789), or None when it is not
    a plausible Taiwan phone (see `phone_problem` for why)."""
    return phone_digits(text) if phone_problem(text) is None else None
