"""Pages: 模擬群組上傳, 總表 and 上傳紀錄, driven over HTTP."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _post_upload(client, file_bytes: bytes, *, uploader="Udemo-TC01", filename="TC01.xlsx"):
    return client.post(
        "/demo/upload",
        data={"uploader_line_id": uploader},
        files={"file": (filename, file_bytes, XLSX)},
    )


def _order_nos(html: str) -> list[str]:
    return re.findall(r'<td class="order-no">([^<]*)</td>', html)


def test_demo_upload_page_is_marked_demo_only_and_lists_demo_uploaders(client):
    html = client.get("/demo/upload").text

    assert "demo 用，門市不會看到" in html
    assert "Udemo-TC01" in html
    assert "台中中正店 門市帳號" in html


def test_uploading_on_the_demo_page_shows_the_reply(client, clean_file):
    resp = _post_upload(client, clean_file)

    assert resp.status_code == 200
    assert "台中中正店（TC01）：收到 2 張喜餅訂單、3 筆訂單明細。" in resp.text
    assert "demo 用，門市不會看到" in resp.text


def test_master_list_filters_by_store_and_pickup_date(client, clean_file, make_template_file):
    _post_upload(client, clean_file)
    ch01 = make_template_file(
        "CH01",
        [("CH-1", "張太太", "0933-111-222", date(2026, 10, 19), date(2026, 11, 28), None,
          "許文傑、周怡君", "淑惠", "咖哩大餅", 30, None, None)],
    )
    _post_upload(client, ch01, uploader="Udemo-CH01", filename="CH01.xlsx")

    def listed(**params) -> list[str]:
        return _order_nos(client.get("/orders", params=params).text)

    assert listed() == ["CH-1", "0201", "0201", "0202"]
    assert listed(store="TC01") == ["0201", "0201", "0202"]
    assert listed(pickup_on="2026-11-28") == ["CH-1", "0201", "0201"]
    assert listed(store="TC01", pickup_on="2026-11-28") == ["0201", "0201"]
    assert listed(store="", pickup_on="") == ["CH-1", "0201", "0201", "0202"]


def test_upload_history_offers_the_original_file_for_download(client, clean_file):
    _post_upload(client, clean_file, filename="中正店 10月.xlsx")

    history = client.get("/uploads").text
    assert "中正店 10月.xlsx" in history
    assert "台中中正店（TC01）：收到 2 張喜餅訂單、3 筆訂單明細。" in history
    link = re.search(r'href="(/uploads/\d+/original)"', history)[1]

    resp = client.get(link)
    assert resp.status_code == 200
    assert resp.content == clean_file
    assert quote("中正店 10月.xlsx") in resp.headers["content-disposition"]
