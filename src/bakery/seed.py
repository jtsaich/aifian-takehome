"""Reference data: 門市 and 品項 (with 品項別名) from the catalog, plus the demo 傳檔者.

Insert-if-missing, so rerunning never overwrites what HQ later edits on the web.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bakery.catalog import PRODUCTS, STORES
from bakery.models import Product, ProductAlias, Store, Uploader

# (line_user_id, display_name): one shared store account per 門市, plus a personal
# account so the demo shows a 門市 with more than one 傳檔者.
DEMO_UPLOADERS: tuple[tuple[str, str], ...] = (
    *((f"Udemo-{s.code}", f"{s.name} 門市帳號") for s in STORES),
    ("Udemo-TC01-meiling", "美玲（台中中正店）"),
)


def seed_reference_data(session: Session) -> None:
    session.execute(
        insert(Store).values([{"code": s.code, "name": s.name} for s in STORES]).on_conflict_do_nothing()
    )
    session.execute(
        insert(Product)
        .values([{"code": p.code, "name": p.name} for p in PRODUCTS])
        .on_conflict_do_nothing()
    )
    aliases = [{"product_code": p.code, "alias": a} for p in PRODUCTS for a in p.aliases]
    session.execute(insert(ProductAlias).values(aliases).on_conflict_do_nothing())
    session.execute(
        insert(Uploader)
        .values(
            [{"line_user_id": uid, "display_name": name, "is_demo": True} for uid, name in DEMO_UPLOADERS]
        )
        .on_conflict_do_nothing()
    )
