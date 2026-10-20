"""Reference data: 門市 and 品項 (with 品項別名) from the catalog, plus the demo 傳檔者;
and the demo web accounts.

Insert-if-missing, so rerunning never overwrites what HQ later edits on the web.
"""

from __future__ import annotations

from functools import cache

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bakery.accounts import hash_password
from bakery.catalog import PRODUCTS, STORES
from bakery.models import Account, Product, ProductAlias, Role, Store, Uploader

# (line_user_id, display_name): one shared store account per 門市, plus a personal
# account so the demo shows a 門市 with more than one 傳檔者.
DEMO_UPLOADERS: tuple[tuple[str, str], ...] = (
    *((f"Udemo-{s.code}", f"{s.name} 門市帳號") for s in STORES),
    ("Udemo-TC01-meiling", "美玲（台中中正店）"),
)

# (username, display_name, role): one account per 總部人員, one shared 廚房 account and
# one 老闆 account. Every demo account uses DEMO_PASSWORD; both are listed in README.
DEMO_ACCOUNTS: tuple[tuple[str, str, Role], ...] = (
    ("hq-lin", "林雅文（總部）", Role.HQ),
    ("hq-chen", "陳志明（總部）", Role.HQ),
    ("kitchen", "中央廚房", Role.KITCHEN),
    ("owner", "老闆", Role.OWNER),
)
DEMO_PASSWORD = "demo1234"


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


def seed_demo_accounts(session: Session) -> None:
    session.execute(insert(Account).values(_demo_account_rows()).on_conflict_do_nothing())


@cache
def _demo_account_rows() -> list[dict]:
    # Hashed once per process: argon2 is deliberately slow and tests reseed before every test.
    password_hash = hash_password(DEMO_PASSWORD)
    return [
        {"username": u, "display_name": n, "role": r, "password_hash": password_hash}
        for u, n, r in DEMO_ACCOUNTS
    ]
