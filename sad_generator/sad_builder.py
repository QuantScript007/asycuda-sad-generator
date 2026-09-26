"""Write the ASYCUDA++ SAD workbook (.xls) and the blank input template.

The cell layout is unchanged from v2.2 so existing import workflows keep
working; v3 adds header styling, column widths and a selectable preferential
tariff (general / SAFTA / CMFTA).
"""

from __future__ import annotations

import io

import xlwt

from .duty import calculate_item_duty, check_preferential
from .utils import normalize_hs_code

_HEADER_STYLE = xlwt.easyxf(
    "font: bold on; align: wrap on, vert centre; "
    "pattern: pattern solid, fore_colour pale_blue; borders: bottom thin"
)
_TOTAL_STYLE = xlwt.easyxf("font: bold on; borders: top thin")


def _num(val, default=""):
    if val in (None, ""):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def create_sad_workbook(data: dict, preferential: str = "general") -> bytes:
    """Build the SAD .xls from ``{"general": {...}, "items": [...]}``."""
    preferential = check_preferential(preferential)
    wb = xlwt.Workbook(encoding="utf-8")
    g = data["general"]
    items = data["items"]

    def gv(key, default=""):
        return g.get(key, g.get(key.replace("_", " "), default))

    ws = wb.add_sheet("General Segment")
    ws.write(0, 0, "S.A.D Field Nbr", _HEADER_STYLE)
    ws.write(0, 1, "Descriptions", _HEADER_STYLE)
    ws.write(0, 2, "Values", _HEADER_STYLE)
    for col, width in enumerate((16, 26, 34, 12)):
        ws.col(col).width = 256 * width

    std_rows = [
        (1, "A", "Customs clearance office", gv("customs_office", "00MP"), None),
        (2, "", "Manifest No.", gv("manifest_no", ""), None),
        (3, 29, "Office of entry/exit", gv("office_entry_exit", gv("customs_office", "00MP")), None),
        (4, 1, "Model of declaration", gv("decl_type", "IM"), gv("decl_subtype", 4)),
        (5, 37, "Procedure", gv("procedure", "4000"), gv("procedure_add", "000")),
        (6, 2, "Exporter", gv("exporter", ""), None),
        (7, 8, "Consignee", gv("consignee_code", "C8888"), None),
        (8, 14, "Declarant", gv("declarant_code", "C8888"), None),
        (9, 13, "Sector", gv("sector", ""), None),
        (10, 9, "Financial", gv("financial", ""), None),
        (11, 15, "Country of export", gv("country_of_export", ""), None),
        (12, 18, "Name of the Vessel", gv("vessel_name", ""), None),
        (13, 20, "Delivery terms", gv("delivery_terms", "CIF"), None),
    ]
    for (ri, fn, desc, v2, v3) in std_rows:
        if fn:
            ws.write(ri, 0, fn)
        ws.write(ri, 1, desc)
        if v2 not in ("", None):
            ws.write(ri, 2, v2)
        if v3 not in ("", None):
            ws.write(ri, 3, v3)

    ws.write(14, 0, 22)
    ws.write(14, 1, "Total amount invoiced")
    ws.write(14, 2, _num(gv("invoice_amount", 0), 0))
    ws.write(14, 3, gv("invoice_currency", "USD"))

    for ri, label, key, cur_key in [
        (15, "Internal Freight", "internal_freight", None),
        (16, "External Freight", "external_freight", "freight_currency"),
        (17, "Insurance", "insurance", "insurance_currency"),
        (18, "Other costs", "other_costs", "other_costs_currency"),
    ]:
        ws.write(ri, 1, label)
        v = _num(gv(key))
        if v != "":
            ws.write(ri, 2, v)
        if cur_key:
            ws.write(ri, 3, gv(cur_key, "USD"))

    ws.write(19, 1, "Deductions")
    if gv("deductions", ""):
        ws.write(19, 2, gv("deductions"))

    ws.write(20, 0, 30); ws.write(20, 1, "Location of goods")
    ws.write(20, 2, gv("location_goods", gv("location_of_goods", "")))
    ws.write(21, 1, "Working mode")
    ws.write(21, 2, _num(gv("working_mode", 0), 0))
    ws.write(22, 0, "48"); ws.write(22, 1, "Pre-Payment Code")
    ws.write(22, 2, str(gv("prepayment_code", gv("pre_payment_code", ""))))
    ws.write(23, 0, "40"); ws.write(23, 1, "BL Number")
    ws.write(23, 2, str(gv("bl_number", "")))
    ws.write(24, 0, "25"); ws.write(24, 1, "Mode of Transport")
    ws.write(24, 2, str(gv("mode_transport", gv("mode_of_transport", "1"))))
    ws.write(25, 0, "27"); ws.write(25, 1, "Place of Discharge")
    ws.write(25, 2, str(gv("place_discharge", gv("place_of_discharge", ""))))
    ws.write(26, 0, "18"); ws.write(26, 1, "Carrier Nationality")
    ws.write(26, 2, gv("carrier_nationality", "MV"))
    ws.write(27, 0, "11"); ws.write(27, 1, "Trading Country")
    ws.write(27, 2, gv("trading_country", ""))
    ws.write(28, 0, "6"); ws.write(28, 1, "Total No. of Package")
    ws.write(28, 2, _num(gv("total_packages", 0), 0))

    wi = wb.add_sheet("Items")
    # Row 1: Field number header
    wi.write(1, 0, "Field Nbr")
    wi.write(1, 1, "33"); wi.write(1, 2, "41")
    wi.write(1, 3, "34"); wi.write(1, 4, "35"); wi.write(1, 5, "36")
    wi.write(1, 6, "42"); wi.write(1, 7, "Valuation")
    wi.write(1, 8, "43 V.M."); wi.write(1, 9, "43 D.Val")
    wi.write(1, 10, "43 D.aty"); wi.write(1, 11, "43 NPR")
    wi.write(1, 12, "47 Type"); wi.write(1, 13, "47 Base")
    wi.write(1, 14, "47 Rate"); wi.write(1, 15, "47 Amount")
    wi.write(1, 21, "31 Packages and description of goods")

    # Row 2: Human-readable column headers
    headers = [
        (0,  "Item\nnumber"),
        (1,  "Commodity\ncode"),
        (2,  "Supplementary\nunits"),
        (3,  "Country\nof origin"),
        (4,  "Gross mass"),
        (5,  "Preference"),
        (6,  "Item\nprice"),
        (7,  "Internal\nFreight"),
        (8,  "Valuation\nMethod (V.M.)"),
        (9,  "Customs\nValue (D.Val)"),
        (10, "Duty Rate\n(%) (D.aty)"),
        (11, "Duty Amount\n(NPR)"),
        (12, "Tax Type\n(IPV/RVF)"),
        (13, "Tax\nBase"),
        (14, "Tax Rate\n(%)"),
        (15, "Tax\nAmount"),
        (16, "External\nFreight"),
        (17, "Insurance"),
        (18, "Other\ncosts"),
        (19, "Deductions"),
        (20, "Unit Nos"),
        (21, "Commercial Description of Goods"),
        (22, "Packing 1st"),
        (23, "Packing Code 1"),
        (24, "Packing 3rd"),
        (25, "Packing Code 2"),
        (26, "Brand"),
        (27, "Model"),
        (28, "Size"),
        (29, "Package Code"),
        (30, "No. of\nPackages"),
    ]
    for col, lbl in headers:
        wi.write(2, col, lbl, _HEADER_STYLE)
        wi.col(col).width = 256 * (44 if col == 21 else 13)
    wi.row(2).height_mismatch = True
    wi.row(2).height = 20 * 30

    for idx, item in enumerate(items):
        r = 3 + idx

        def iv(key, default="", item=item):
            return item.get(key, item.get(key.replace("_", " "), default))

        wi.write(r, 0, idx + 1)
        wi.write(r, 1, normalize_hs_code(iv("hs_code", "")))
        su = _num(iv("supp_units", iv("supplementary_units")))
        if su != "":
            wi.write(r, 2, su)
        wi.write(r, 3, str(iv("country_origin", iv("country_of_origin", ""))))
        gm = _num(iv("gross_mass"))
        if gm != "":
            wi.write(r, 4, gm)
        pref = iv("preference", "")
        if pref:
            wi.write(r, 5, pref)
        ip = _num(iv("item_price"))
        if ip != "":
            wi.write(r, 6, ip)

        # Box 43: Valuation & Duty rate (customs duty percentage)
        duty_info = calculate_item_duty(item, preferential)
        wi.write(r, 8, "1")  # V.M. = transaction value method 1
        if ip != "":
            wi.write(r, 9, float(ip))  # D.Val (customs value = item price)
        if duty_info["duty_rate"] is not None:
            wi.write(r, 10, duty_info["duty_rate"])  # D.aty %
        if duty_info["duty_amount"] > 0:
            wi.write(r, 11, duty_info["duty_amount"])  # NPR (duty amount)
            # Box 47: Tax calculation (IPV = Import duty)
            wi.write(r, 12, "IPV")
            wi.write(r, 13, float(ip))
            wi.write(r, 14, duty_info["duty_rate"])
            wi.write(r, 15, duty_info["duty_amount"])

        # Cols 7, 16-19: Internal Freight, External, Insurance, Other, Deductions
        for col, key_a, key_b in [
            (7,  "int_freight", "internal_freight"),
            (16, "ext_freight", "external_freight"),
            (17, "insurance",   "insurance"),
            (18, "other_costs", "other_costs"),
            (19, "deductions",  "deductions"),
        ]:
            v = _num(iv(key_a, iv(key_b)))
            if v != "":
                wi.write(r, col, v)
        un = _num(iv("unit_nos"))
        if un != "":
            wi.write(r, 20, un)
        wi.write(r, 21, str(iv("description", iv("commercial_description", ""))))
        p1 = _num(iv("packing1", iv("packing_1st")))
        if p1 != "":
            wi.write(r, 22, p1)
        wi.write(r, 23, str(iv("packing_code1", iv("packing_code_1", ""))))
        p3 = _num(iv("packing3", iv("packing_3rd")))
        if p3 != "":
            wi.write(r, 24, p3)
        wi.write(r, 25, str(iv("packing_code2", iv("packing_code_2", ""))))
        wi.write(r, 26, str(iv("brand", "")))
        wi.write(r, 27, str(iv("model", "")))
        wi.write(r, 28, str(iv("size", "")))
        wi.write(r, 29, str(iv("package_code", "")))
        npkg = _num(iv("no_packages", iv("no_of_packages")))
        if npkg != "":
            wi.write(r, 30, npkg)

    # Totals row
    total_row = 3 + len(items)
    total_duty = round(sum(calculate_item_duty(it, preferential)["duty_amount"] for it in items), 2)
    wi.write(total_row, 0, "TOTAL", _TOTAL_STYLE)
    wi.write(total_row, 6, round(sum(_num(it.get("item_price", 0), 0) for it in items), 2), _TOTAL_STYLE)
    wi.write(total_row, 11, total_duty, _TOTAL_STYLE)
    wi.write(total_row, 15, total_duty, _TOTAL_STYLE)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create_input_template() -> bytes:
    """Blank input template (Declaration + Items sheets) with one sample row."""
    wb = xlwt.Workbook(encoding="utf-8")
    bold = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour pale_blue")

    ws1 = wb.add_sheet("Declaration")
    decl_headers = [
        "customs_office", "manifest_no", "office_entry_exit",
        "decl_type", "decl_subtype", "procedure", "procedure_add",
        "exporter", "consignee_code", "declarant_code",
        "sector", "financial", "country_of_export",
        "vessel_name", "delivery_terms",
        "invoice_amount", "invoice_currency",
        "internal_freight", "external_freight", "freight_currency",
        "insurance", "insurance_currency",
        "other_costs", "other_costs_currency",
        "deductions", "location_goods", "working_mode",
        "prepayment_code", "bl_number", "mode_transport",
        "place_discharge", "carrier_nationality",
        "trading_country", "total_packages",
    ]
    sample_decl = [
        "00MP", "", "00MP", "IM", 4, "4000", "000",
        "SUPPLIER NAME", "C8888", "C8888",
        "", "", "CN", "VESSEL NAME HERE", "CIF",
        45000, "USD", 0, 4000, "USD",
        300, "USD", 130.75, "USD",
        0, "HBW", 0, "", "BL123456", "1",
        "MLE", "MV", "CN", 1,
    ]
    for col, (h, v) in enumerate(zip(decl_headers, sample_decl)):
        ws1.write(0, col, h, bold)
        ws1.write(1, col, v)

    ws2 = wb.add_sheet("Items")
    item_headers = [
        "hs_code", "supp_units", "country_origin", "gross_mass",
        "preference", "item_price", "int_freight", "ext_freight",
        "insurance", "other_costs", "deductions",
        "unit_nos", "description",
        "packing1", "packing_code1", "packing3", "packing_code2",
        "brand", "model", "size", "package_code", "no_packages",
    ]
    sample_items = [
        "0603120011", "", "CN", 3.0,
        "", 5000.0, 0, 0, 0, 0, 0,
        100, "Rice - Sample Description",
        7.514, "NMB", 2.354, "NMB",
        "", "", "", "1G", 23,
    ]
    for col, (h, v) in enumerate(zip(item_headers, sample_items)):
        ws2.write(0, col, h, bold)
        ws2.write(1, col, v)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
