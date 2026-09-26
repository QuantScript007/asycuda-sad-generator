import asyncio
import io

import openpyxl
import xlrd

from sad_generator import service
from sad_generator.excel_io import read_input_excel
from sad_generator.hs_lookup import enrich_items_hs_codes
from sad_generator.sad_builder import create_input_template, create_sad_workbook


def _run(coro):
    return asyncio.run(coro)


def test_template_roundtrip(tmp_path):
    path = tmp_path / "template.xls"
    path.write_bytes(create_input_template())
    data = read_input_excel(path)
    assert data["general"]["bl_number"] == "BL123456"
    assert data["items"][0]["hs_code"] == "0603120011"
    assert data["items"][0]["description"].startswith("Rice")


def test_xlsx_template_with_numeric_hs_and_aliases(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Declaration"
    ws.append(["bl_number", "vessel_name", "invoice_currency"])
    ws.append(["MSC/001", "MV TEST", "EUR"])
    items = wb.create_sheet("Items")
    items.append(["HS Code", "Commercial Description", "Country of Origin", "item_price"])
    items.append([603120011, "Carnations", "KE", 1000])   # numeric → lost leading zero
    items.append([None, "Basmati rice", "IN", 500])
    path = tmp_path / "in.xlsx"
    wb.save(path)

    data = read_input_excel(path)
    assert data["items"][0]["hs_code"] == "0603120011"
    assert data["items"][0]["description"] == "Carnations"
    assert data["items"][0]["country_origin"] == "KE"

    result = _run(service.generate(data))
    assert result.output_path.name.startswith("SAD_MSC-001_")
    assert result.hs_auto_filled == 1                      # rice looked up by description
    assert result.items[1]["hs_code"] == "1006300099"
    assert result.duty_summary["total_duty"] == 250.0      # 25% of 1000 + 0% of 500
    assert result.duty_summary["currency"] == "EUR"


def test_generated_sad_can_be_reimported(tmp_path):
    data = {
        "general": {"bl_number": "BL9", "invoice_currency": "USD"},
        "items": [
            {"hs_code": "6403990099", "description": "Sandals", "item_price": 100, "gross_mass": 5,
             "packing1": 1, "packing_code1": "NMB", "brand": "X", "no_packages": 3},
            {"hs_code": "1006300099", "description": "Rice", "item_price": 50},
        ],
    }
    result = _run(service.generate(data))
    back = read_input_excel(result.output_path)
    # The TOTAL row must not come back as a phantom item
    assert len(back["items"]) == 2
    first = back["items"][0]
    assert first["hs_code"] == "6403990099"
    assert first["description"] == "Sandals"
    assert first["brand"] == "X"
    assert first["no_packages"] == 3
    assert first["duty_rate"] == 20


def test_sad_layout_and_preferential_totals():
    data = {"general": {"bl_number": "B"}, "items": [
        {"hs_code": "6403990099", "item_price": 1000, "duty_rate": 20, "safta_rate": 15, "description": "Shoes"},
    ]}
    wb = xlrd.open_workbook(file_contents=create_sad_workbook(data, "safta"))
    assert wb.sheet_names() == ["General Segment", "Items"]
    items = wb.sheet_by_name("Items")
    assert items.cell_value(1, 10) == "43 D.aty"
    assert items.cell_value(3, 1) == "6403990099"
    assert items.cell_value(3, 10) == 15.0
    assert items.cell_value(3, 11) == 150.0
    assert items.cell_value(3, 21) == "Shoes"
    assert items.cell_value(4, 0) == "TOTAL"
    assert items.cell_value(4, 11) == 150.0


def test_manual_form_duty_strings_are_understood(offline_lookup):
    # The browser form sends "20%" (or "⏳" while a lookup is still running)
    items = [
        {"hs_code": "6403990099", "description": "Sandals", "item_price": 100,
         "duty_rate": "20%", "duty_amount": "$20.00", "total_with_duty": "$120.00"},
        {"hs_code": "0603120011", "description": "Flowers", "item_price": 100, "duty_rate": "⏳"},
    ]
    out = _run(enrich_items_hs_codes(items))
    assert out[0]["duty_rate"] == 20.0
    assert "duty_amount" not in out[0]
    assert out[1]["duty_rate"] == 25.0          # "⏳" discarded → looked up
    assert out[0]["safta_rate"] == 15.0         # preferential rates filled in


def test_no_lookup_mode_makes_no_requests(offline_lookup):
    out = _run(enrich_items_hs_codes([{"description": "rice", "item_price": 1}], lookup=False))
    assert offline_lookup == []
    assert out[0]["hs_code"] == ""


def test_input_workbook_is_readable_from_bytes(tmp_path):
    raw = create_input_template()
    xlrd.open_workbook(file_contents=io.BytesIO(raw).getvalue())
