import struct

import olefile
import xlrd

from sad_generator.excel_io import read_input_excel
from sad_generator.sad_model import blank_model_bytes, create_sad_model_workbook, model_path


def _record_counts(data: bytes) -> dict:
    import io
    stream = olefile.OleFileIO(io.BytesIO(data)).openstream("Workbook").read()
    counts, i = {}, 0
    while i + 4 <= len(stream):
        rt, ln = struct.unpack_from("<HH", stream, i)
        counts[rt] = counts.get(rt, 0) + 1
        i += 4 + ln
    return counts


GENERAL = {
    "customs_office": "00MP", "bl_number": "MSKU1234567", "vessel_name": "MV DEMO", "exporter": "ACME",
    "country_of_export": "CN", "invoice_amount": 1500, "invoice_currency": "EUR",
    "external_freight": 200, "freight_currency": "EUR", "total_packages": 7, "trading_country": "CN",
}
ITEMS = [
    {"hs_code": 603120011, "description": "Fresh carnations", "country_origin": "KE", "gross_mass": 12.5,
     "item_price": 1000, "unit_nos": 100, "packing1": 1, "packing_code1": "NMB", "brand": "Bloom",
     "package_code": "PK", "no_packages": 4},
    {"hs_code": "8418102000", "description": "X" * 60, "item_price": 500, "brand": "B" * 30,
     "ext_freight": 20, "no_packages": 3},
]


def test_model_layout_matches_template():
    out, warnings = create_sad_model_workbook({"general": GENERAL, "items": ITEMS})
    wb = xlrd.open_workbook(file_contents=out, formatting_info=True)
    ref = xlrd.open_workbook(str(model_path()), formatting_info=True)
    assert wb.sheet_names() == ["General Segment", "Items"]
    g, it = wb.sheet_by_index(0), wb.sheet_by_index(1)
    rg, rit = ref.sheet_by_index(0), ref.sheet_by_index(1)

    # Labels, merged cells, column widths and cell styles are the model's
    for r in range(29):
        assert g.cell_value(r, 1) == rg.cell_value(r, 1)
    assert [it.cell_value(2, c) for c in range(30)] == [rit.cell_value(2, c) for c in range(30)]
    assert it.merged_cells == rit.merged_cells
    assert [it.colinfo_map[c].width for c in range(30)] == [rit.colinfo_map[c].width for c in range(30)]
    for c in range(30):
        assert it.cell_xf_index(3, c) == rit.cell_xf_index(3, c)
    assert g.cell_value(1, 9) == "00MP"                     # office list for the dropdown kept

    # Values
    assert g.cell_value(12, 2) == "MV DEMO" and g.cell_value(23, 2) == "MSKU1234567"
    assert g.cell_value(14, 2) == 1500 and g.cell_value(14, 3) == "EUR"
    assert g.cell_value(16, 2) == 200 and g.cell_value(16, 3) == "EUR"
    assert g.cell_value(17, 2) == "" and g.cell_value(17, 3) == ""   # no insurance → no currency
    assert g.cell_value(4, 2) == "IM" and g.cell_value(5, 3) == "000"
    assert it.cell_value(3, 0) == 1 and it.cell_value(3, 1) == "0603120011"
    assert it.cell_value(3, 20) == "Fresh carnations" and it.cell_value(3, 29) == 4
    assert it.cell_value(4, 9) == 20 and it.cell_value(4, 10) == "EUR"   # item-level freight + currency
    assert it.cell_value(5, 20) == "" and it.cell_value(5, 1) == ""       # template sample rows cleared

    # ASYCUDA field limits
    assert it.cell_value(4, 20) == "X" * 49 and it.cell_value(4, 25) == "B" * 24
    assert len(warnings) == 2


def test_dropdowns_and_comments_are_preserved():
    out, _ = create_sad_model_workbook({"general": GENERAL, "items": ITEMS * 30})
    before, after = _record_counts(model_path().read_bytes()), _record_counts(out)
    for rec in (0x01BE, 0x01B2, 0x001C, 0x005D, 0x00EC, 0x00E5, 0x007D):   # DV, DVAL, NOTE, OBJ, MSODRAWING, MERGE, COLINFO
        assert after.get(rec) == before.get(rec), hex(rec)


def test_model_roundtrip_and_blank_model(tmp_path):
    out, _ = create_sad_model_workbook({"general": GENERAL, "items": ITEMS})
    p = tmp_path / "sad.xls"
    p.write_bytes(out)
    back = read_input_excel(p)
    assert back["general"]["bl_number"] == "MSKU1234567"
    assert back["general"]["invoice_currency"] == "EUR"
    assert [i["hs_code"] for i in back["items"]] == ["0603120011", "8418102000"]

    blank = tmp_path / "blank.xls"
    blank.write_bytes(blank_model_bytes())
    data = read_input_excel(blank)
    assert data["items"] == [] and "vessel_name" not in data["general"]


def test_many_items():
    items = [{"hs_code": "8418102000", "description": f"Item {i}", "item_price": i} for i in range(1, 1201)]
    out, _ = create_sad_model_workbook({"general": GENERAL, "items": items})
    it = xlrd.open_workbook(file_contents=out).sheet_by_index(1)
    assert it.cell_value(1202, 0) == 1200 and it.cell_value(1202, 20) == "Item 1200"
