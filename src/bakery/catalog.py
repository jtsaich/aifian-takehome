"""Seed data for 品項 (with 品項別名) and 門市.

Single source of truth: the template dropdowns, the mock data and (later) the
database seed all read from here. After go-live HQ maintains products in the
web admin; this module is only the initial seed.
"""

from __future__ import annotations

from dataclasses import dataclass

BRAND_NAME = "金禾餅舖"


@dataclass(frozen=True)
class Product:
    code: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Store:
    code: str
    name: str


PRODUCTS: tuple[Product, ...] = (
    Product("P01", "龍鳳喜餅", ("龍鳳餅", "龍鳳")),
    Product("P02", "鳳梨酥禮盒", ("鳳梨酥",)),
    Product("P03", "綠豆椪禮盒", ("綠豆椪",)),
    Product("P04", "太陽餅禮盒", ("太陽餅",)),
    Product("P05", "咖哩大餅", ("咖哩餅",)),
    Product("P06", "綜合西式喜餅", ("西式喜餅", "西餅")),
    Product("P07", "蛋黃酥禮盒", ()),
)

STORES: tuple[Store, ...] = (
    Store("TC01", "台中中正店"),
    Store("TC02", "台中北屯店"),
    Store("TC03", "豐原中山店"),
    Store("CH01", "彰化中華店"),
    Store("CH02", "員林光明店"),
    Store("NT01", "草屯和平店"),
)


def product_names() -> list[str]:
    """Canonical 品項 names, in catalog order (what the template dropdown shows)."""
    return [p.name for p in PRODUCTS]


def store_by_code(code: str) -> Store:
    for s in STORES:
        if s.code == code:
            return s
    raise KeyError(code)
