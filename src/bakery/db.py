"""Engine creation, Alembic upgrade and the `bakery-init` command (migrate + seed)."""

from __future__ import annotations

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

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


def init_main() -> None:
    """`bakery-init`: bring the schema to head, seed reference data and the demo
    accounts. Safe to rerun."""
    url = database_url()
    upgrade_database(url)
    engine = make_engine(url)
    with Session(engine) as session:
        seed_reference_data(session)
        seed_demo_accounts(session)
        session.commit()
    engine.dispose()
