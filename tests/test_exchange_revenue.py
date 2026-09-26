import asyncio

import xlrd
from fastapi.testclient import TestClient

from sad_generator import exchange, service
from sad_generator.app import app
from sad_generator.duty import calculate_item_duty
from sad_generator.exchange import parse_exchange_table, resolve_rate


def test_item_duty_and_revenue_in_mvr():
    d = calculate_item_duty({"item_price": 1000, "duty_rate": 20}, fx_rate=15.42)
    assert d["value_mvr"] == 15420.0      # 1000 × 15.42
    assert d["duty_mvr"] == 3084.0        # 1000 × 20% × 15.42
    assert d["revenue_mvr"] == 154.2      # 1000 × 15.42 × 0.01
    assert d["payable_mvr"] == 3238.2
    zero = calculate_item_duty({"item_price": 500, "duty_rate": 0}, fx_rate=15.42)
    assert zero["duty_mvr"] == 0 and zero["revenue_mvr"] == 77.1
    assert "duty_mvr" not in calculate_item_duty({"item_price": 1, "duty_rate": 5})


def test_parse_exchange_table_variants():
    html = """<table>
      <tr><th>Code</th><th>Currency</th><th>Rate</th></tr>
      <tr><td>USD</td><td>US Dollar</td><td>15.42</td></tr>
      <tr><td>EUR</td><td>Euro</td><td>16,8012</td></tr>
      <tr><td>JPY</td><td>100</td><td>10.50</td></tr>
      <tr><td>Total</td><td>x</td></tr>
    </table>"""
    rates = parse_exchange_table(html)
    assert rates["USD"] == 15.42
    assert rates["JPY"] == 0.105           # quoted per 100 units
    assert rates["MVR"] == 1.0
    assert "EUR" in rates


def test_resolve_rate_order(monkeypatch):
    run = asyncio.run
    assert run(resolve_rate("usd", "15.5"))["source"] == "manual"
    assert run(resolve_rate("EUR")) == {"currency": "EUR", "rate": 16.8, "source": "customs"}
    assert run(resolve_rate("MVR"))["rate"] == 1.0

    async def offline(force=False):
        return {}
    monkeypatch.setattr(exchange, "fetch_rates", offline)
    assert run(resolve_rate("USD")) == {"currency": "USD", "rate": 15.42, "source": "fallback"}
    assert run(resolve_rate("GBP"))["source"] == "missing"


def test_generate_writes_mvr_totals_and_columns():
    data = {"general": {"bl_number": "FX1", "invoice_currency": "USD"},
            "items": [{"hs_code": "6403990099", "description": "Sandals", "item_price": 1000},
                      {"hs_code": "1006300099", "description": "Rice", "item_price": 500}]}
    r = asyncio.run(service.generate(data))
    s = r.duty_summary
    assert s["exchange_rate"] == 15.42 and s["exchange_source"] == "customs"
    assert s["total_duty_mvr"] == 3084.0            # 20% sandals only
    assert s["total_revenue_mvr"] == 231.3          # 1500 × 15.42 × 1%
    assert s["total_payable_mvr"] == 3315.3
    assert r.analytics["mvr"]["payable"] == 3315.3
    assert r.items_preview[0]["revenue_mvr"] == 154.2

    ws = xlrd.open_workbook(str(r.duty_sheet_path)).sheet_by_name("Items")
    assert ws.cell_value(2, 33).startswith("Duty (MVR)")
    assert ws.cell_value(3, 31) == 15.42 and ws.cell_value(3, 33) == 3084.0 and ws.cell_value(3, 34) == 154.2
    assert ws.cell_value(5, 0) == "TOTAL" and ws.cell_value(5, 35) == 3315.3
    g = xlrd.open_workbook(str(r.duty_sheet_path)).sheet_by_name("General Segment")
    assert g.cell_value(30, 2) == 15.42 and g.cell_value(33, 2) == 3315.3


def test_manual_rate_override_and_api():
    client = TestClient(app)
    body = client.post("/api/generate-manual", json={
        "general": {"bl_number": "M1", "invoice_currency": "USD"},
        "items": [{"hs_code": "6403990099", "description": "Sandals", "item_price": 100, "duty_rate": 20}],
        "exchange_rate": 15.5,
    }).json()
    ds = body["duty_summary"]
    assert ds["exchange_rate"] == 15.5 and ds["exchange_source"] == "manual"
    assert ds["total_duty_mvr"] == 310.0 and ds["total_revenue_mvr"] == 15.5
    rates = client.get("/api/exchange-rates", params={"currency": "EUR"}).json()
    assert rates["selected"]["rate"] == 16.8 and rates["revenue_rate"] == 0.01
