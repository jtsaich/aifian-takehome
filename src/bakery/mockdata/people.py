"""Fake names and phone numbers. Everything here is made up."""

from __future__ import annotations

import random

_SURNAMES = "陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高"
_GIVEN_FEMALE = "雅婷 怡君 淑芬 美玲 佳穎 欣怡 宜蓁 詩涵 佩君 惠如 雅雯 婉婷 心怡 筱涵 靜宜".split()
_GIVEN_MALE = "志明 家豪 俊傑 建宏 冠宇 承翰 柏翰 宗翰 彥廷 信宏 文雄 國華 明哲 品睿 俊宏".split()
_NOTES = ("", "", "", "", "附提袋", "分兩箱裝", "喜帖袋另外拿", "要附發票", "請先電話確認")


class People:
    """Deterministic source of fake people for one generator run."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._used_phones: set[str] = set()

    def female(self) -> str:
        return self._rng.choice(_SURNAMES) + self._rng.choice(_GIVEN_FEMALE)

    def male(self) -> str:
        return self._rng.choice(_SURNAMES) + self._rng.choice(_GIVEN_MALE)

    def orderer(self) -> str:
        return self.female() if self._rng.random() < 0.7 else self.male()

    def couple(self) -> str:
        return f"{self.male()}、{self.female()}"

    def note(self) -> str:
        return self._rng.choice(_NOTES)

    def mobile_digits(self) -> str:
        """A fresh 10-digit mobile number (09xxxxxxxx), never repeated within a run."""
        while True:
            digits = "09" + "".join(str(self._rng.randrange(10)) for _ in range(8))
            if digits not in self._used_phones:
                self._used_phones.add(digits)
                return digits

    def landline_digits(self, area: str) -> str:
        """A fresh 10-digit landline with area code (04xxxxxxxx, 049xxxxxxx)."""
        while True:
            digits = area + "".join(str(self._rng.randrange(10)) for _ in range(10 - len(area)))
            if digits not in self._used_phones:
                self._used_phones.add(digits)
                return digits


def format_phone(digits: str, style: str) -> str:
    """Write a phone the way a given store's staff types it.

    Styles: plain, dash, space, intl (+886). Normalizing these back to one
    number is ticket 09's job; the mock files just exercise it.
    """
    if style == "plain":
        return digits
    if digits.startswith("09"):
        a, b, c = digits[:4], digits[4:7], digits[7:]
        styles = {"dash": f"{a}-{b}-{c}", "space": f"{a} {b} {c}", "intl": f"+886 {a[1:]} {b} {c}"}
    else:
        area_len = 3 if digits.startswith("049") else 2
        area, rest = digits[:area_len], digits[area_len:]
        styles = {
            "dash": f"{area}-{rest[:-4]}-{rest[-4:]}",
            "space": f"({area}){rest[:-4]}-{rest[-4:]}",
            "intl": f"+886 {area[1:]} {rest}",
        }
    return styles[style]
