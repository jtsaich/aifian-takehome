"""電話正規化: every way a 門市 writes the same phone lands on one 客人; the rest get a warning."""

from __future__ import annotations

import pytest

from bakery.phone import PhoneProblem, normalize_phone, phone_problem


@pytest.mark.parametrize(
    ("typed", "normalized"),
    [
        # 手機
        ("0912345678", "0912345678"),
        ("0912-345-678", "0912345678"),
        ("0912 345 678", "0912345678"),
        ("0912-345678", "0912345678"),
        (" 0912 - 345 - 678 ", "0912345678"),
        ("(0912)345-678", "0912345678"),
        ("0912.345.678", "0912345678"),
        ("０９１２－３４５－６７８", "0912345678"),  # full-width, typed with a Chinese IME
        ("912345678", "0912345678"),  # number cell: Excel dropped the leading 0
        # +886
        ("+886912345678", "0912345678"),
        ("+886 912 345 678", "0912345678"),
        ("+886-912-345-678", "0912345678"),
        ("+886 (0)912 345 678", "0912345678"),
        ("+886 0912-345-678", "0912345678"),
        ("+886-4-2345-6789", "0423456789"),
        # 含區碼的市話
        ("04-2345-6789", "0423456789"),
        ("04 2345 6789", "0423456789"),
        ("(04)2345-6789", "0423456789"),
        ("0423456789", "0423456789"),
        ("02-2345-6789", "0223456789"),
        ("049-547-4284", "0495474284"),
        ("04-2345678", "042345678"),  # 7-digit local number
        ("037-123456", "037123456"),
        ("082-312345", "082312345"),
    ],
)
def test_ways_of_writing_one_phone_normalize_to_the_same_digits(typed, normalized):
    assert normalize_phone(typed) == normalized
    assert phone_problem(typed) is None


@pytest.mark.parametrize(
    ("typed", "problem"),
    [
        ("0912-3456", PhoneProblem.TOO_SHORT),
        ("0915-7116", PhoneProblem.TOO_SHORT),
        ("+886 912 345", PhoneProblem.TOO_SHORT),
        ("04-234567", PhoneProblem.TOO_SHORT),
        ("0912-345-6789", PhoneProblem.TOO_LONG),
        ("04-2345-67890", PhoneProblem.TOO_LONG),
        ("2345-6789", PhoneProblem.MALFORMED),  # landline without 區碼
        ("09123x5678", PhoneProblem.MALFORMED),
        ("0912-345-678 #12", PhoneProblem.MALFORMED),
        ("0912-345-678、04-2345-6789", PhoneProblem.MALFORMED),  # two phones in one cell
        ("00886912345678", PhoneProblem.MALFORMED),
        ("王小姐", PhoneProblem.MALFORMED),
        ("-", PhoneProblem.MALFORMED),
    ],
)
def test_phone_that_cannot_be_normalized_says_why(typed, problem):
    assert normalize_phone(typed) is None
    assert phone_problem(typed) == problem


def test_different_phones_stay_different():
    assert normalize_phone("0912-345-678") != normalize_phone("0912-345-679")
    assert normalize_phone("04-2345-6789") != normalize_phone("02-2345-6789")
