"""The demo script (`bakery-demo`): the story replays end to end, and it never wipes
a database that is not local unless told to."""

from __future__ import annotations

import pytest

from bakery import demo
from bakery.demo import DemoError, Reset, Site, prepare_files, replay, reset_plan
from conftest import NOW

NEON = "postgresql://u:p@ep-cool-1.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
CLOUD_RUN = "https://bakery-orders-abc-de.a.run.app"


def test_the_story_replays_on_an_empty_database(make_client, tmp_path, capsys):
    http = make_client(None)
    http.follow_redirects = False
    files = prepare_files(tmp_path, NOW.date(), NOW)

    replay(Site(http, NOW.date()), files)

    out = capsys.readouterr().out
    assert "== 9. 匯入歷史資料 ==" in out
    assert "單號 0106：追加，綠豆椪禮盒 50→70 盒（已過截止點，待總部確認）" in out


def test_the_story_refuses_a_database_that_already_has_orders(make_client, tmp_path):
    http = make_client(None)
    http.follow_redirects = False
    files = prepare_files(tmp_path, NOW.date(), NOW)
    site = Site(http, NOW.date())
    replay(site, files)

    with pytest.raises(DemoError, match="已經有訂單"):
        replay(site, files)


def test_reset_targets_local_compose_or_a_local_database_url():
    assert reset_plan("http://localhost:8000", None, wipe_remote=False) is Reset.COMPOSE
    local_db = "postgresql://bakery:bakery@127.0.0.1:5432/bakery"
    assert reset_plan("http://127.0.0.1:8000", local_db, wipe_remote=False) is Reset.DATABASE_URL


@pytest.mark.parametrize(
    ("base_url", "database_url"),
    [(CLOUD_RUN, None), (CLOUD_RUN, NEON), ("http://localhost:8000", NEON)],
)
def test_reset_refuses_a_non_local_target_without_wipe_remote(base_url, database_url):
    with pytest.raises(DemoError):
        reset_plan(base_url, database_url, wipe_remote=False)


def test_reset_of_a_remote_database_needs_both_the_url_and_the_flag():
    assert reset_plan(CLOUD_RUN, NEON, wipe_remote=True) is Reset.DATABASE_URL
    with pytest.raises(DemoError, match="--database-url"):
        reset_plan(CLOUD_RUN, None, wipe_remote=True)


def test_refused_remote_reset_touches_nothing(monkeypatch, tmp_path):
    def untouchable(*args, **kwargs):
        raise AssertionError("must not run")

    for name in ("init_database", "prepare_files", "reset_database"):
        monkeypatch.setattr(demo, name, untouchable)

    code = demo.main(["--base-url", CLOUD_RUN, "--reset", "--database-url", NEON, "--out", str(tmp_path)])

    assert code == 1
