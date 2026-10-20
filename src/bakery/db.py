"""Engine creation, Alembic upgrade and the `bakery-init` command (migrate + seed)."""

from __future__ import annotations

import argparse
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from bakery.models import Base
from bakery.seed import seed_demo_accounts, seed_reference_data


def database_url() -> str:
    """DATABASE_URL from the environment, pointed at the psycopg 3 driver.

    Accepts the plain `postgres://` / `postgresql://` URLs hosting providers hand out.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "bakery:migrations")
    # ConfigParser interpolation: a literal % in the URL (encoded password) must be doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade_database(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def wipe_data(session: Session) -> None:
    """Empty every table (the schema stays). Demo and tests only: this deletes the
    append-only uploads and change log too (TRUNCATE bypasses their row triggers)."""
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def seed(session: Session) -> None:
    seed_reference_data(session)
    seed_demo_accounts(session)


def init_database(url: str, *, wipe: bool = False) -> None:
    """Bring the schema to head, optionally empty it, then seed. Safe to rerun."""
    upgrade_database(url)
    engine = make_engine(url)
    with Session(engine) as session:
        if wipe:
            wipe_data(session)
        seed(session)
        session.commit()
    engine.dispose()


def init_main(argv: list[str] | None = None) -> None:
    """`bakery-init`: bring the schema to head, seed reference data and the demo
    accounts. Safe to rerun. `--wipe-all-data` empties the database first (the demo
    script's reset of the local compose database)."""
    parser = argparse.ArgumentParser(description="資料庫升到最新版本，並種入參考資料與 demo 帳號")
    parser.add_argument("--wipe-all-data", action="store_true", help="先清空所有資料（只給 demo 用）")
    args = parser.parse_args(argv)
    init_database(database_url(), wipe=args.wipe_all_data)
