"""Scan invoice: text parsing, mapping to form fields, tariff-anchored HS codes, Claude path (mocked)."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from sad_generator import config, hs_lookup, invoice_scan
from sad_generator.app import app

client = TestClient(app)

INVOICE_TEXT = """HARBOURLINE TRADING PTE LTD
COMMERCIAL INVOICE
Invoice No: HLT-24-0917      Date: 14/09/2026
Currency: USD   Terms: FOB Singapore
B/L No: MSCUSG1234567  Vessel: MSC ANNA
No  Description                         Qty  Unit  Unit Price  Amount
1   Basmati rice 5kg bag                 120  BAG   14.50      1,740.00
2   Leather sandals men                  600  PRS   3.85       2,310.00
3   LED bulb E27 9W warm white           800  pcs   0.95       760.00
Sub Total                                                    4,810.00
Grand Total USD                                              4,810.00
Total packages: 38 cartons   Gross weight: 612.4 KGS   Net weight: 548.0 KGS
Freight: 420.00  Insurance: 32.00
"""


@pytest.fixture
def tariff_prefix(monkeypatch):
    """Extend the offline tariff stub with heading (6-digit prefix) searches."""
    base = hs_lookup._search

    async def search(term):
        t = term.strip()
        if t == "100630":
            return [{"hs_code": "1006300011", "description": "Parboiled rice", "duty_rate": 0.0},
                    {"hs_code": "1006300099", "description": "Other rice, basmati", "duty_rate": 0.0}]
        if t == "853952":
            return [{"hs_code": "8539520000", "description": "LED lamps", "duty_rate": 25.0}]
        return await base(term)

    monkeypatch.setattr(hs_lookup, "_search", search)


def test_parse_amount_formats():
    assert invoice_scan.parse_amount("1,740.00") == 1740.0
    assert invoice_scan.parse_amount("1.740,50") == 1740.5
    assert invoice_scan.parse_amount("12,50") == 12.5
    assert invoice_scan.parse_amount("$ 3.85") == 3.85
    assert invoice_scan.parse_amount("—") is None


def test_parse_invoice_text_header_and_items():
    raw = invoice_scan.parse_invoice_text(INVOICE_TEXT)
    h = raw["header"]
    assert h["supplier_name"] == "HARBOURLINE TRADING PTE LTD"
    assert h["invoice_no"] == "HLT-24-0917"
    assert h["currency"] == "USD" and h["incoterm"] == "FOB"
    assert h["bl_awb_no"] == "MSCUSG1234567" and h["transport_mode"] == "Sea"
    assert h["invoice_total"] == 4810.0 and h["total_packages"] == 38
    assert h["gross_weight_kg"] == 612.4 and h["freight"] == 420.0
    assert [i["description"] for i in raw["items"]] == [
        "Basmati rice 5kg bag", "Leather sandals men", "LED bulb E27 9W warm white"]
    first = raw["items"][0]
    assert (first["quantity"], first["unit"], first["unit_price"], first["total_price"]) == (120, "BAG", 14.5, 1740.0)
    assert raw["items"][1]["unit"] == "PR"


def test_to_form_maps_fields_allocates_weight_and_checks():
    form = invoice_scan.to_form(invoice_scan.parse_invoice_text(INVOICE_TEXT), engine="text")
    g = form["general"]
    assert g["bl_number"] == "MSCUSG1234567" and g["delivery_terms"] == "FOB"
    assert g["invoice_amount"] == 4810.0 and g["invoice_currency"] == "USD"
    assert g["external_freight"] == 420.0 and g["insurance"] == 32.0 and g["mode_transport"] == "1"
    items = form["items"]
    assert items[0]["item_price"] == 1740.0 and items[0]["supp_units"] == 120
    # shipment gross weight spread over the lines by value
    assert round(sum(i["gross_mass"] for i in items), 1) == 612.4
    assert all(i["gross_mass_allocated"] for i in items)
    levels = {c["text"].split(" ")[0]: c["level"] for c in form["checks"]}
    assert levels["Every"] == "ok" and levels["Lines"] == "ok"
    assert form["invoice"]["invoice_no"] == "HLT-24-0917"


def test_resolve_hs_prefers_tariff_codes_under_suggested_heading(tariff_prefix):
    items = [
        {"description": "Basmati rice 5kg bag", "hs_suggested": "100630"},
        {"description": "LED bulb", "hs_suggested": "853952"},
        {"description": "Leather sandals men"},              # no suggestion → description search
        {"description": "Unknown gizmo", "hs_suggested": "999999"},
    ]
    asyncio.run(invoice_scan.resolve_hs_codes(items))
    assert items[0]["hs_code"] == "1006300099"            # best word overlap with "basmati"
    assert items[0]["hs_source"] == "tariff" and len(items[0]["hs_candidates"]) == 2
    assert items[1]["hs_code"] == "8539520000" and items[1]["duty_rate"] == 25.0
    assert items[2]["hs_code"] == "6403990099" and items[2]["hs_source"] == "search"
    assert items[3]["hs_code"] == "999999" and items[3]["hs_source"] == "suggested"


def test_resolve_hs_description_search_ranked_by_word_overlap(monkeypatch):
    async def search(term):
        return [{"hs_code": "1006300011", "description": "Parboiled rice", "duty_rate": 0.0},
                {"hs_code": "1006300099", "description": "Other rice, basmati", "duty_rate": 0.0}]

    monkeypatch.setattr(hs_lookup, "_search", search)
    items = [{"description": "Basmati rice 5kg bag"}]
    asyncio.run(invoice_scan.resolve_hs_codes(items))
    assert items[0]["hs_code"] == "1006300099" and items[0]["hs_source"] == "search"


def test_scan_text_endpoint(tariff_prefix):
    r = client.post("/api/scan-text", json={"text": INVOICE_TEXT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "text" and len(body["items"]) == 3
    assert body["items"][1]["hs_code"] == "6403990099"


def test_scan_status_and_missing_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    assert client.get("/api/scan/status").json()["server_key"] is False
    r = client.post("/api/scan", files={"files": ("inv.png", b"x", "image/png")})
    assert r.status_code == 400 and "API key" in r.json()["detail"]


CLAUDE_REPLY = """```json
{"header":{"supplier_name":"Harbourline Trading","supplier_address":"Singapore","supplier_country":"SG",
 "currency":"USD","invoice_total":1740,"incoterm":"CIF","transport_mode":"Air","bl_awb_no":"176-12345675",
 "total_packages":10,"gross_weight_kg":186},
 "items":[{"description":"Basmati rice 5kg bag","brand":"Golden","hs_code":"1006.30","hs_confidence":"high",
 "origin":"IN","quantity":120,"unit":"BAG","unit_price":14.5,"total_price":1740,"packages":10,
 "package_type":"CTN","gross_weight_kg":186,"net_weight_kg":168}],
 "notes":["Stamp covers part of the date."]}
```"""


def test_scan_with_claude_mocked(monkeypatch, tariff_prefix):
    sent = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            sent.update(url=url, body=json, headers=headers)
            return httpx.Response(200, json={"content": [{"type": "text", "text": CLAUDE_REPLY}]})

    monkeypatch.setattr(invoice_scan.httpx, "AsyncClient", FakeClient)
    r = client.post("/api/scan", headers={"X-Anthropic-Key": "sk-ant-test"},
                    files=[("files", ("inv.pdf", b"%PDF-1.4", "application/pdf")),
                           ("files", ("pl.jpg", b"\xff\xd8", "image/jpeg"))])
    assert r.status_code == 200, r.text
    body = r.json()
    blocks = sent["body"]["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["document", "image", "text"]
    assert sent["headers"]["x-api-key"] == "sk-ant-test"
    assert body["engine"] == "claude"
    assert body["general"]["exporter"] == "Harbourline Trading, Singapore"
    assert body["general"]["mode_transport"] == "2" and body["general"]["bl_number"] == "176-12345675"
    it = body["items"][0]
    assert it["brand"] == "Golden" and it["country_origin"] == "IN" and it["no_packages"] == 10
    assert it["hs_code"] == "1006300099" and it["hs_confidence"] == "high"
    assert body["notes"] == ["Stamp covers part of the date."]


def test_scan_with_claude_reports_api_errors(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return httpx.Response(400, json={"error": {"message": "Your credit balance is too low"}})

    monkeypatch.setattr(invoice_scan.httpx, "AsyncClient", FakeClient)
    r = client.post("/api/scan", headers={"X-Anthropic-Key": "sk-ant-test"},
                    files={"files": ("inv.png", b"x", "image/png")})
    assert r.status_code == 400 and "no credit" in r.json()["detail"]
