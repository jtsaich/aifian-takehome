"""convert-legacy: each 門市's pre-go-live Excel into the 範本, checked against the 對照表."""

from __future__ import annotations

import io
import json
import re
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from bakery.catalog import PRODUCTS
from bakery.legacy import ConversionError, convert, main
from bakery.parsing import ProductRef, parse_upload

MOCK = Path(__file__).resolve().parents[1] / "mock_data"
MANIFEST = json.loads((MOCK / "expectations.json").read_text())
LEGACY = {lg["store_code"]: lg for lg in MANIFEST["legacy"]}
TODAY = date(2026, 10, 21)

LOOKUP = {
    name: ProductRef(p.code, p.name) for p in PRODUCTS for name in (p.name, *p.aliases)
}


def _converted(store_code: str):
    """The converted 範本 as the import will read it."""
    content = convert(store_code, (MOCK / LEGACY[store_code]["file"]).read_bytes()).content
    return parse_upload(content, LOOKUP, TODAY)


@pytest.mark.parametrize("store_code", sorted(LEGACY))
def test_converted_file_has_the_orders_the_mock_data_table_lists(store_code):
    parsed = _converted(store_code)

    assert parsed.store_code == store_code
    assert parsed.findings == () and parsed.rejected_rows == ()
    got = [
        (o.orderer_name, o.phone, o.received_on.isoformat(), o.pickup_on.isoformat(),
         {line.product_name: line.quantity for line in o.lines})
        for o in parsed.orders
    ]
    expected = [
        (o["orderer_name"], o["phone"], o["received_on"], o["pickup_on"], o["lines"])
        for o in LEGACY[store_code]["orders"]
    ]
    assert got == expected


@pytest.mark.parametrize("store_code", sorted(LEGACY))
def test_every_order_gets_a_historical_order_no(store_code):
    order_nos = [o.order_no for o in _converted(store_code).orders]

    assert len(set(order_nos)) == len(order_nos)
    assert all(re.fullmatch(r"H-\d{8}-\d{2}", no) for no in order_nos), order_nos


def test_order_no_is_h_then_received_date_then_a_sequence():
    assert [o.order_no for o in _converted("TC02").orders][:2] == ["H-20260523-01", "H-20260609-01"]


def test_ch01_keeps_banquet_day_and_couple_from_the_old_columns():
    first = _converted("CH01").orders[0]

    assert first.banquet_on == date(2026, 6, 22)
    assert first.couple_names == "張明哲、黃欣怡"


def test_tc02_note_is_kept_once_per_order():
    first = _converted("TC02").orders[0]

    assert [line.note for line in first.lines] == ["分兩箱裝", None]


@pytest.mark.parametrize("store_code", sorted(LEGACY))
def test_conversion_is_byte_for_byte_reproducible(store_code):
    source = (MOCK / LEGACY[store_code]["file"]).read_bytes()

    assert convert(store_code, source).content == convert(store_code, source).content


def test_cli_writes_the_converted_file_and_rerunning_gives_the_same_bytes(tmp_path, capsys):
    source = MOCK / LEGACY["TC02"]["file"]
    out = tmp_path / "TC02.xlsx"

    assert main(["TC02", str(source), "-o", str(out)]) == 0
    first = out.read_bytes()
    assert main(["TC02", str(source), "-o", str(out)]) == 0

    assert out.read_bytes() == first == convert("TC02", source.read_bytes()).content
    assert "7 張喜餅訂單、11 筆訂單明細" in capsys.readouterr().out


def _tc02_file(*rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "喜餅登記"
    ws.append(["接單日期", "客人", "電話", "龍鳳", "鳳梨酥", "綠豆椪", "其他", "取貨日", "備註"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_a_date_the_converter_cannot_read_stops_the_conversion_and_says_where():
    source = _tc02_file(
        ("115/05/23", "王小姐", "0912345678", 60, None, None, None, "下週六", None),
        ("115/05/24", "李先生", "0922345678", 10, None, None, None, "6/8", None),
    )

    with pytest.raises(ConversionError) as exc:
        convert("TC02", source)

    assert exc.value.problems == (
        "喜餅登記 第 2 列：取貨日「下週六」看不懂，要有年月日。",
        "喜餅登記 第 3 列：取貨日「6/8」看不懂，要有年月日。",
    )


def test_cli_reports_problems_and_writes_nothing(tmp_path, capsys):
    source = tmp_path / "old.xlsx"
    source.write_bytes(_tc02_file(("115/05/23", "王小姐", "0912345678", None, None, None, "月餅", "115/06/08", None)))
    out = tmp_path / "out.xlsx"

    assert main(["TC02", str(source), "-o", str(out)]) == 1

    assert not out.exists()
    assert "喜餅登記 第 2 列：其他欄寫「月餅」，看不出品項和盒數（例如「太陽餅20盒」）。" in capsys.readouterr().err


def test_names_not_in_the_product_list_are_kept_as_written_and_listed(capsys, tmp_path):
    source = tmp_path / "old.xlsx"
    source.write_bytes(_tc02_file(("115/05/23", "王小姐", "0912345678", None, None, None, "月下10盒", "115/06/08", None)))

    assert main(["TC02", str(source), "-o", str(tmp_path / "out.xlsx")]) == 0

    assert "不在商品清單裡：月下" in capsys.readouterr().out
