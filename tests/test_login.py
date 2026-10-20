"""角色登入: who can log in, what each role may open, and what anonymous visitors get."""

from __future__ import annotations

import base64
import json
import re

import pytest
from fastapi.routing import APIRoute
from itsdangerous import TimestampSigner
from sqlalchemy import select

from bakery.db import init_main
from bakery.models import Account, Upload
from bakery.pipeline import process_upload
from bakery.seed import DEMO_PASSWORD
from bakery.web.app import ROUTERS, create_app
from bakery.web.auth import DEV_SESSION_SECRET, SESSION_COOKIE

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Routes anyone may reach without logging in. Adding a public route means adding it
# here on purpose (the LINE webhook will: it checks LINE's signature instead).
PUBLIC = {("GET", "/"), ("GET", "/login"), ("POST", "/login"), ("POST", "/logout")}

# Every logged-in page, as registered, with the demo accounts that may open it
# (ticket 05: 廚房 sees only 總表 and 廚房彙總; 總部人員 and 老闆 see everything here).
PAGES: dict[str, set[str]] = {
    "/orders": {"hq-lin", "hq-chen", "kitchen", "owner"},
    "/uploads": {"hq-lin", "hq-chen", "owner"},
    "/uploads/{upload_id}": {"hq-lin", "hq-chen", "owner"},
    "/uploads/{upload_id}/original": {"hq-lin", "hq-chen", "owner"},
    "/demo/upload": {"hq-lin", "hq-chen", "owner"},
}
ACCOUNTS = ("hq-lin", "hq-chen", "kitchen", "owner")


def _registered_routes(engine) -> set[tuple[str, str]]:
    """(method, path) of every route the app serves: its own plus every router in ROUTERS."""
    routes = [r for r in create_app(engine).routes if isinstance(r, APIRoute)]
    routes += [r for router, _ in ROUTERS for r in router.routes if isinstance(r, APIRoute)]
    return {(method, r.path) for r in routes for method in r.methods}


def _url(path: str) -> str:
    return path.replace("{upload_id}", "1")


def _upload(client, file_bytes: bytes):
    return client.post(
        "/demo/upload",
        data={"uploader_line_id": "Udemo-TC01"},
        files={"file": ("TC01.xlsx", file_bytes, XLSX)},
    )


@pytest.fixture
def orders_exist(client, clean_file):
    """One file sent as 總部人員, so there is order data (and upload 1) to protect."""
    assert _upload(client, clean_file).status_code == 200


@pytest.mark.parametrize(
    ("username", "display_name"),
    [("hq-lin", "林雅文（總部）"), ("hq-chen", "陳志明（總部）"), ("kitchen", "中央廚房"), ("owner", "老闆")],
)
def test_each_demo_account_logs_in_with_the_readme_password(make_client, username, display_name):
    c = make_client(None)

    resp = c.post("/login", data={"username": username, "password": "demo1234"})

    assert resp.status_code == 200
    assert resp.url.path == "/orders"
    assert display_name in resp.text


@pytest.mark.parametrize(
    ("username", "password"), [("hq-lin", "wrong"), ("nobody", DEMO_PASSWORD), ("hq-lin", "")]
)
def test_wrong_credentials_are_refused(make_client, orders_exist, username, password):
    c = make_client(None)

    resp = c.post("/login", data={"username": username, "password": password})

    assert resp.status_code in (401, 422)
    assert c.get("/orders", follow_redirects=False).status_code == 303


def test_wrong_password_shows_an_error_on_the_login_page(make_client):
    resp = make_client(None).post("/login", data={"username": "hq-lin", "password": "wrong"})

    assert resp.status_code == 401
    assert "帳號或密碼錯誤" in resp.text


def test_every_page_except_login_requires_an_account(engine, make_client, orders_exist):
    anon = make_client(None)
    guarded = _registered_routes(engine) - PUBLIC
    assert guarded, "no guarded routes found"

    for method, path in sorted(guarded):
        resp = anon.request(method, _url(path), follow_redirects=False)
        assert resp.status_code == 303, (method, path)
        assert resp.headers["location"].startswith("/login?next="), (method, path)


def test_anonymous_visitors_see_no_order_data(make_client, orders_exist):
    anon = make_client(None)

    for path in ("/", "/orders", "/uploads", "/uploads/1/original", "/demo/upload"):
        resp = anon.get(path)
        assert resp.url.path == "/login", path
        for secret in ("0201", "王小姐", "0912-345-678", "陳志豪", "台中中正店"):
            assert secret not in resp.text, (path, secret)
        assert "總表" not in resp.text  # no nav links either


def test_anonymous_upload_is_refused_and_stores_nothing(make_client, session, clean_file):
    resp = _upload(make_client(None), clean_file)

    assert resp.url.path == "/login"
    assert session.scalars(select(Upload)).all() == []


def test_every_logged_in_page_is_in_the_access_table(engine):
    guarded_paths = {path for _, path in _registered_routes(engine) - PUBLIC}

    assert guarded_paths == set(PAGES)


@pytest.mark.parametrize("username", ACCOUNTS)
def test_each_role_is_blocked_from_pages_it_should_not_see(make_client, orders_exist, username):
    c = make_client(username)

    for path, allowed in PAGES.items():
        resp = c.get(_url(path), follow_redirects=False)
        if username in allowed:
            assert resp.status_code == 200, (username, path)
        else:
            assert resp.status_code == 403, (username, path)
            assert "0201" not in resp.text and "王小姐" not in resp.text


def test_kitchen_cannot_upload_from_the_demo_page(make_client, session, clean_file):
    resp = _upload(make_client("kitchen"), clean_file)

    assert resp.status_code == 403
    assert session.scalars(select(Upload)).all() == []


def test_kitchen_nav_shows_only_the_master_list(make_client):
    html = make_client("kitchen").get("/orders").text
    nav = re.search(r"<nav>(.*?)</nav>", html, re.S)[1]

    assert 'href="/orders"' in nav
    assert 'href="/uploads"' not in nav
    assert 'href="/demo/upload"' not in nav


def test_login_returns_to_the_page_first_asked_for(make_client):
    c = make_client(None)
    login_page = c.get("/uploads?x=1")
    assert login_page.url.path == "/login"

    next_value = re.search(r'name="next" value="([^"]*)"', login_page.text)[1]
    resp = c.post("/login", data={"username": "owner", "password": DEMO_PASSWORD, "next": next_value})

    assert resp.url.path == "/uploads"
    assert resp.url.query == b"x=1"


@pytest.mark.parametrize("next_url", ["https://evil.example/", "//evil.example/", "/\\evil.example"])
def test_login_never_redirects_off_site(make_client, next_url):
    resp = make_client(None).post(
        "/login",
        data={"username": "owner", "password": DEMO_PASSWORD, "next": next_url},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_logout_ends_the_session(client):
    assert client.get("/orders", follow_redirects=False).status_code == 200

    client.post("/logout")

    assert client.get("/orders", follow_redirects=False).status_code == 303


def test_a_forged_session_cookie_is_not_accepted(make_client, orders_exist):
    anon = make_client(None)
    payload = base64.b64encode(json.dumps({"account_id": 1}).encode())
    forged = TimestampSigner("not-the-server-secret").sign(payload).decode()
    anon.cookies.set(SESSION_COOKIE, forged)

    assert anon.get("/orders", follow_redirects=False).status_code == 303


def test_demo_upload_records_which_account_sent_it(make_client, session, now, clean_file):
    process_upload(
        session, uploader_line_id="Udemo-CH01", filename="line.xlsx", file_bytes=clean_file, now=now
    )
    _upload(make_client("hq-chen"), clean_file)

    rows = re.findall(r'<td class="submitted-by">([^<]*)</td>', make_client("owner").get("/uploads").text)
    assert rows == ["模擬群組上傳：陳志明（總部）", "LINE"]


def test_passwords_are_stored_hashed(session):
    accounts = session.scalars(select(Account)).all()

    assert {a.username for a in accounts} == set(ACCOUNTS)
    for a in accounts:
        assert DEMO_PASSWORD not in a.password_hash
        assert a.password_hash.startswith("$argon2id$")


def test_bakery_init_seeds_the_demo_accounts_and_can_rerun(monkeypatch, database_url, make_client):
    monkeypatch.setenv("DATABASE_URL", database_url)

    init_main()
    init_main()

    assert make_client("hq-chen").get("/orders", follow_redirects=False).status_code == 200


def test_production_refuses_to_start_without_a_session_secret(monkeypatch, engine):
    monkeypatch.setenv("BAKERY_ENV", "production")
    for secret in (None, DEV_SESSION_SECRET, "short"):
        if secret is None:
            monkeypatch.delenv("SESSION_SECRET", raising=False)
        else:
            monkeypatch.setenv("SESSION_SECRET", secret)
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            create_app(engine)

    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    create_app(engine)


def test_development_runs_on_the_default_secret(monkeypatch, engine):
    monkeypatch.delenv("BAKERY_ENV", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    create_app(engine)
