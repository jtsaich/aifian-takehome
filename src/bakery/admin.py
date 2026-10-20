"""What 總部 maintains on the web: the 修改截止點 (N days) and the 品項 list with its 品項別名.

A new 品項 or 品項別名 counts from the next upload on: a row refused for an unknown
品項 is taken in when the 門市 sends the file again.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bakery.models import Product, ProductAlias, Settings

# The 範本's 品項 cell is matched exactly after trimming (bakery.parsing), so names are
# stored trimmed; a 品項 name and every 品項別名 share one namespace.
MAX_NAME_LENGTH = 64
MAX_CUTOFF_DAYS = 60


class AdminError(ValueError):
    """Refused input; the message is the 繁中 explanation shown on the page."""


def cutoff_days(session: Session) -> int:
    return session.get(Settings, 1).cutoff_days


def set_cutoff_days(session: Session, days: int) -> None:
    if not 0 <= days <= MAX_CUTOFF_DAYS:
        raise AdminError(f"截止天數要填 0 到 {MAX_CUTOFF_DAYS} 之間的整數。")
    session.get(Settings, 1).cutoff_days = days
    session.commit()


def products(session: Session) -> list[Product]:
    return list(
        session.scalars(select(Product).options(selectinload(Product.aliases)).order_by(Product.code))
    )


def add_product(session: Session, name: str) -> Product:
    """A new 品項, coded after the last one (P08 after P07)."""
    name = _checked_name(session, name)
    numbers = [int(m[1]) for code in session.scalars(select(Product.code)) if (m := re.fullmatch(r"P(\d+)", code))]
    product = Product(code=f"P{max(numbers, default=0) + 1:02d}", name=name)
    session.add(product)
    session.commit()
    return product


def add_alias(session: Session, product_code: str, alias: str) -> ProductAlias:
    if session.get(Product, product_code) is None:
        raise AdminError("找不到這個品項。")
    record = ProductAlias(product_code=product_code, alias=_checked_name(session, alias))
    session.add(record)
    session.commit()
    return record


def _checked_name(session: Session, text: str) -> str:
    name = text.strip()
    if not name:
        raise AdminError("名稱不能空白。")
    if len(name) > MAX_NAME_LENGTH:
        raise AdminError(f"名稱最多 {MAX_NAME_LENGTH} 個字。")
    taken = session.scalar(select(Product.name).where(Product.name == name)) or session.scalar(
        select(ProductAlias.alias).where(ProductAlias.alias == name)
    )
    if taken:
        raise AdminError(f"「{name}」已經是品項或品項別名了。")
    return name
