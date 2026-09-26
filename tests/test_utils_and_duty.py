import pytest

from sad_generator.duty import build_items_preview_and_duty, calculate_item_duty
from sad_generator.hs_lookup import parse_tariff_rows
from sad_generator.utils import normalize_hs_code, parse_rate, safe_filename_part


@pytest.mark.parametrize("raw, expected", [
    ("0603120011", "0603120011"),
    (603120011, "0603120011"),          # Excel dropped the leading zero
    (603120011.0, "0603120011"),
    ("603120011.0", "0603120011"),
    ("0603.12.00.11", "0603120011"),    # the old .replace(".0", "") left "0603.120.11"
    ("8422 19 0000", "8422190000"),
    ("0603.0120", "06030120"),
    ("", ""),
    (None, ""),
    (0, ""),
    ("0", ""),
])
def test_normalize_hs_code(raw, expected):
    assert normalize_hs_code(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("15%", 15.0), (" 12.5 % ", 12.5), (0, 0.0), ("0.00", 0.0),
    ("", None), ("—", None), ("⏳", None), ("??", None), (None, None),
])
def test_parse_rate(raw, expected):
    assert parse_rate(raw) == expected


def test_safe_filename_part():
    assert safe_filename_part('MSC/123:45*"x"') == "MSC-123-45-x"
    assert safe_filename_part("", "manual") == "manual"


def test_duty_general_and_preferential():
    item = {"item_price": 1000, "duty_rate": 20, "safta_rate": 15, "cmfta_rate": None}
    assert calculate_item_duty(item)["duty_amount"] == 200.0
    assert calculate_item_duty(item, "safta")["duty_amount"] == 150.0
    # CMFTA not published for this code → falls back to general rate
    assert calculate_item_duty(item, "cmfta")["duty_amount"] == 200.0


def test_duty_accepts_string_rate_and_missing_rate():
    assert calculate_item_duty({"item_price": "200", "duty_rate": "10%"})["duty_amount"] == 20.0
    d = calculate_item_duty({"item_price": 50})
    assert d["duty_rate"] is None and d["total_with_duty"] == 50.0


def test_summary_covers_all_items_not_just_preview():
    items = [{"item_price": 10, "duty_rate": 10}] * 120
    preview, summary = build_items_preview_and_duty(items, currency="EUR", preview_limit=50)
    assert len(preview) == 50
    assert summary["total_item_value"] == 1200.0
    assert summary["total_duty"] == 120.0
    assert summary["currency"] == "EUR"


def test_parse_tariff_rows():
    html = """<table>
      <tr><th>Code</th><th>Description</th><th>Unit</th><th>Rate</th></tr>
      <tr><td>6403 9900 99</td><td>Other footwear</td><td>PR</td><td>20</td><td></td>
          <td>15</td><td></td><td>5.5</td><td></td><td>…</td></tr>
      <tr><td>6403990099</td><td>duplicate</td></tr>
    </table>"""
    rows = parse_tariff_rows(html)
    assert rows == [{
        "hs_code": "6403990099", "description": "Other footwear", "hs_unit": "PR",
        "duty_rate": 20.0, "safta_rate": 15.0, "cmfta_rate": 5.5,
    }]


def test_analytics():
    from sad_generator.analytics import build_analytics

    general = {"invoice_amount": 1500, "external_freight": 100, "insurance": 10, "total_packages": 9}
    items = [
        {"hs_code": "6403990099", "country_origin": "CN", "item_price": 1000, "duty_rate": 20,
         "gross_mass": 50, "no_packages": 5, "description": "Shoes"},
        {"hs_code": "1006300099", "country_origin": "IN", "item_price": 400, "duty_rate": 0,
         "gross_mass": 950, "no_packages": 4, "_hs_looked_up": True},
        {"hs_code": "", "country_origin": "cn", "item_price": 100},
    ]
    a = build_analytics(general, items)
    assert a["totals"]["duty"] == 200.0 and a["totals"]["effective_rate"] == 13.33
    assert a["totals"]["packages"] == 9 and a["totals"]["gross_mass"] == 1000.0
    assert a["cost_breakdown"]["cif"] == 1610.0 and a["cost_breakdown"]["landed"] == 1810.0
    assert a["reconciliation"]["matches"] is True
    assert a["by_origin"][0]["key"] == "CN" and a["by_origin"][0]["items"] == 2
    assert a["by_chapter"][0]["label"] == "Footwear"
    assert a["hs_sources"] == {"manual": 1, "auto": 1, "missing": 1}
    bands = {b["label"]: b["count"] for b in a["rate_bands"]}
    assert bands["0%"] == 1 and bands["10–20%"] == 1 and bands["Unknown"] == 1
    assert a["top_duty_items"][0]["duty"] == 200.0


def test_analytics_zero_invoice_falls_back_to_items():
    from sad_generator.analytics import build_analytics

    a = build_analytics({"invoice_amount": 0, "external_freight": 50}, [{"item_price": 200, "duty_rate": 10}])
    assert a["cost_breakdown"]["goods"] == 200.0 and a["cost_breakdown"]["cif"] == 250.0
    assert a["reconciliation"]["matches"] is None
