"""Shared fixtures: one real Postgres per test run (testcontainers), schema via Alembic.

Every test starts from freshly seeded reference data (門市, 品項, demo 傳檔者)
and no orders or uploads.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

from bakery.catalog import store_by_code
from bakery.clock import TAIPEI
from bakery.db import upgrade_database
from bakery.models import Base
from bakery.seed import seed_reference_data
from bakery.template import FIRST_DATA_ROW, SHEET_NAME, build_template
from bakery.web.app import create_app
from bakery.web.deps import get_now
from bakery.xlsx import workbook_bytes

# Pinned "now" for every test: 2026-10-21 10:00 in Taipei (mock data day 1).
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=TAIPEI)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        url = pg.get_connection_url()
        upgrade_database(url)
        yield url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        # TRUNCATE bypasses the row-level append-only trigger on uploads.
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        seed_reference_data(s)
        s.commit()
    return factory


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture
def client(engine: Engine, session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app(engine)
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        yield c


# A clean 範本 file for TC01 whose content the tests know literally.
CLEAN_ROWS: tuple[tuple, ...] = (
    # 單號, 訂購人姓名, 電話, 接單日, 取貨日, 宴客日, 新人姓名, 接單人, 品項, 盒數, 備註, 狀態
    ("0201", "王小姐", "0912-345-678", date(2026, 10, 20), date(2026, 11, 28), date(2026, 11, 29),
     "陳志豪、林佳蓉", "美玲", "龍鳳喜餅", 120, "要提袋", None),
    ("0201", "王小姐", "0912-345-678", date(2026, 10, 20), date(2026, 11, 28), date(2026, 11, 29),
     "陳志豪、林佳蓉", "美玲", "鳳梨酥禮盒", 60, None, None),
    ("0202", "李先生", "04-2345-6789", date(2026, 10, 21), date(2026, 12, 5), None,
     "黃冠宇、吳雅婷", None, "綠豆椪禮盒", 40, None, None),
)


def template_file(store_code: str, rows: Sequence[Sequence]) -> bytes:
    """A 範本 .xlsx for `store_code` with `rows` (in COLUMNS order) from the first data row."""
    wb = build_template(store_by_code(store_code))
    ws = wb[SHEET_NAME]
    for r, values in enumerate(rows, start=FIRST_DATA_ROW):
        for c, value in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=value)
    return workbook_bytes(wb, datetime(2026, 10, 21, 9, 0))


@pytest.fixture
def clean_file() -> bytes:
    return template_file("TC01", CLEAN_ROWS)


@pytest.fixture
def make_template_file():
    return template_file


@pytest.fixture
def now() -> datetime:
    return NOW
