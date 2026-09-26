"""Read shipment data from the input template or a native ASYCUDA SAD workbook.

Two layouts are supported for both .xls and .xlsx:

* **Template format** — a ``Declaration`` sheet (headers in row 1, values in
  row 2) and an ``Items`` sheet (headers in row 1, one item per row).
* **Native SAD format** — the ``General Segment`` / ``Items`` layout this tool
  writes, so a generated SAD can be re-loaded, edited and re-generated.
"""

from __future__ import annotations

import openpyxl
import xlrd

from .utils import normalize_hs_code

# Header aliases accepted in the template format (after normalisation).
HEADER_ALIASES = {
    "commodity_code": "hs_code",
    "hs": "hs_code",
    "hscode": "hs_code",
    "tariff_code": "hs_code",
    "commercial_description": "description",
    "description_of_goods": "description",
    "goods_description": "description",
    "country_of_origin": "country_origin",
    "origin": "country_origin",
    "price": "item_price",
    "value": "item_price",
    "no_of_packages": "no_packages",
    "packages": "no_packages",
    "supplementary_units": "supp_units",
}


_NATIVE_GENERAL_DESC_MAP = {
    "customs clearance office": ("customs_office", None),
    "manifest no.": ("manifest_no", None),
    "office of entry/exit": ("office_entry_exit", None),
    "model of declaration": ("decl_type", "decl_subtype"),
    "procedure": ("procedure", "procedure_add"),
    "exporter": ("exporter", None),
    "consignee": ("consignee_code", None),
    "declarant": ("declarant_code", None),
    "sector": ("sector", None),
    "financial": ("financial", None),
    "country of export": ("country_of_export", None),
    "name of the vessel": ("vessel_name", None),
    "delivery terms": ("delivery_terms", None),
    "total amount invoiced": ("invoice_amount", "invoice_currency"),
    "internal freight": ("internal_freight", None),
    "external freight": ("external_freight", "freight_currency"),
    "insurance": ("insurance", "insurance_currency"),
    "other costs": ("other_costs", "other_costs_currency"),
    "deductions": ("deductions", None),
    "location of goods": ("location_goods", None),
    "working mode": ("working_mode", None),
    "pre-payment code": ("prepayment_code", None),
    "bl number": ("bl_number", None),
    "mode of transport": ("mode_transport", None),
    "place of discharge": ("place_discharge", None),
    "carrier nationality": ("carrier_nationality", None),
    "trading country": ("trading_country", None),
    "total no. of package": ("total_packages", None),
}

_NATIVE_ITEMS_COL_MAP = {
    1: "hs_code", 2: "supp_units", 3: "country_origin", 4: "gross_mass",
    5: "preference", 6: "item_price", 7: "int_freight", 9: "ext_freight",
    11: "insurance", 13: "other_costs", 15: "deductions", 19: "unit_nos",
    20: "description", 21: "packing1", 22: "packing_code1", 23: "packing3",
    24: "packing_code2", 25: "brand", 26: "model", 27: "size",
    28: "package_code", 29: "no_packages",
}

# Layout written by this tool (v2.2+): duty/tax columns 8–15 were inserted,
# shifting the cost and description columns to the right. Detected by the
# "43 D.aty" / "Duty Rate" headers so generated SADs can be re-imported.
_GENERATED_ITEMS_COL_MAP = {
    1: "hs_code", 2: "supp_units", 3: "country_origin", 4: "gross_mass",
    5: "preference", 6: "item_price", 7: "int_freight", 10: "duty_rate",
    16: "ext_freight", 17: "insurance", 18: "other_costs", 19: "deductions",
    20: "unit_nos", 21: "description", 22: "packing1", 23: "packing_code1",
    24: "packing3", 25: "packing_code2", 26: "brand", 27: "model", 28: "size",
    29: "package_code", 30: "no_packages",
}


def _native_items_map(header_rows) -> dict:
    text = " ".join(str(v) for row in header_rows for v in row if v not in (None, "")).lower()
    return _GENERATED_ITEMS_COL_MAP if ("d.aty" in text or "duty rate" in text) else _NATIVE_ITEMS_COL_MAP


def _is_total_row(first_cell) -> bool:
    return str(first_cell or "").strip().upper() == "TOTAL"


# ────────────────────────────────────────────────────────────
# Excel Reading Helpers (supports both formats)
# ────────────────────────────────────────────────────────────

def _norm(s) -> str:
    return str(s).strip().lower().replace("\n", "_").replace(" ", "_").replace("-", "_")


def _item_header(s) -> str:
    h = _norm(s) if s not in (None, "") else ""
    return HEADER_ALIASES.get(h, h)


def _read_xls(path: str) -> dict:
    wb = xlrd.open_workbook(path)
    names_lower = [s.lower() for s in wb.sheet_names()]

    def _xls_cell(ws, r, c):
        val = ws.cell_value(r, c)
        ctype = ws.cell_type(r, c)
        if ctype == xlrd.XL_CELL_NUMBER and int(val) == val:
            val = int(val)
        elif ctype == xlrd.XL_CELL_TEXT:
            val = str(val).strip()
        return val

    general: dict = {}
    for cand in ["declaration", "general segment", "general"]:
        if cand in names_lower:
            ws = wb.sheet_by_index(names_lower.index(cand))
            first_cell = str(ws.cell_value(0, 0)).strip().lower() if ws.nrows >= 1 else ""
            if "s.a.d" in first_cell or "field nbr" in first_cell:
                for ri in range(1, ws.nrows):
                    desc = str(ws.cell_value(ri, 1)).strip().lower()
                    if desc not in _NATIVE_GENERAL_DESC_MAP:
                        continue
                    key1, key2 = _NATIVE_GENERAL_DESC_MAP[desc]
                    if ws.ncols > 2:
                        v = _xls_cell(ws, ri, 2)
                        if v not in ("", None):
                            general[key1] = v
                    if key2 and ws.ncols > 3:
                        v2 = _xls_cell(ws, ri, 3)
                        if v2 not in ("", None):
                            general[key2] = v2
            elif ws.nrows >= 2:
                headers = [_norm(ws.cell_value(0, c)) for c in range(ws.ncols)]
                for i, h in enumerate(headers):
                    if not h:
                        continue
                    v = _xls_cell(ws, 1, i)
                    if v not in ("", None):
                        general[h] = v
            break

    items: list = []
    for cand in ["items", "item"]:
        if cand in names_lower:
            ws = wb.sheet_by_index(names_lower.index(cand))
            row0_empty = ws.nrows >= 1 and all(
                ws.cell_value(0, c) in ("", None) for c in range(ws.ncols)
            )
            if row0_empty and ws.nrows >= 4:
                col_map = _native_items_map(
                    [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in (1, 2)]
                )
                for ri in range(3, ws.nrows):
                    if _is_total_row(ws.cell_value(ri, 0)):
                        continue
                    item: dict = {}
                    for col, key in col_map.items():
                        if col >= ws.ncols:
                            continue
                        v = _xls_cell(ws, ri, col)
                        if v not in ("", None):
                            item[key] = v
                    if item:
                        items.append(item)
            elif ws.nrows >= 2:
                headers = [_item_header(ws.cell_value(0, c)) for c in range(ws.ncols)]
                for ri in range(1, ws.nrows):
                    item: dict = {}
                    for i, h in enumerate(headers):
                        if not h:
                            continue
                        v = _xls_cell(ws, ri, i)
                        if v not in ("", None):
                            item[h] = v
                    if item:
                        items.append(item)
            break

    return _finish(general, items)


def _read_xlsx(path: str) -> dict:
    wb = openpyxl.load_workbook(path, data_only=True)
    names_map = {s.lower(): s for s in wb.sheetnames}

    def _norm_xlsx_val(v):
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, float) and int(v) == v:
            return int(v)
        return v

    general: dict = {}
    for cand in ["declaration", "general segment", "general"]:
        if cand in names_map:
            ws = wb[names_map[cand]]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                break
            first_cell = str(rows[0][0] or "").strip().lower()
            if "s.a.d" in first_cell or "field nbr" in first_cell:
                for row in rows[1:]:
                    if len(row) < 2:
                        continue
                    desc = str(row[1] or "").strip().lower()
                    if desc not in _NATIVE_GENERAL_DESC_MAP:
                        continue
                    key1, key2 = _NATIVE_GENERAL_DESC_MAP[desc]
                    v = _norm_xlsx_val(row[2]) if len(row) > 2 else None
                    if v not in (None, ""):
                        general[key1] = v
                    if key2:
                        v2 = _norm_xlsx_val(row[3]) if len(row) > 3 else None
                        if v2 not in (None, ""):
                            general[key2] = v2
            elif len(rows) >= 2:
                headers = [_norm(h) if h else "" for h in rows[0]]
                for i, h in enumerate(headers):
                    if h and i < len(rows[1]) and rows[1][i] not in (None, ""):
                        general[h] = rows[1][i]
            break

    items: list = []
    for cand in ["items", "item"]:
        if cand in names_map:
            ws = wb[names_map[cand]]
            rows = list(ws.iter_rows(values_only=True))
            row0_empty = rows and all(v in (None, "") for v in rows[0])
            if row0_empty and len(rows) >= 4:
                col_map = _native_items_map(rows[1:3])
                for row in rows[3:]:
                    if row and _is_total_row(row[0]):
                        continue
                    item: dict = {}
                    for col, key in col_map.items():
                        if col >= len(row):
                            continue
                        v = _norm_xlsx_val(row[col])
                        if v not in (None, ""):
                            item[key] = v
                    if item:
                        items.append(item)
            elif len(rows) >= 2:
                headers = [_item_header(h) for h in rows[0]]
                for row in rows[1:]:
                    item: dict = {}
                    for i, h in enumerate(headers):
                        if h and i < len(row) and row[i] not in (None, ""):
                            item[h] = row[i]
                    if item:
                        items.append(item)
            break

    return _finish(general, items)


def _finish(general: dict, items: list) -> dict:
    """Normalise HS codes on every item."""
    cleaned = []
    for it in items:
        if "hs_code" in it:
            it["hs_code"] = normalize_hs_code(it["hs_code"])
        cleaned.append(it)
    return {"general": general, "items": cleaned}


def read_input_excel(path) -> dict:
    """Parse an input workbook into ``{"general": {...}, "items": [...]}``."""
    path = str(path)
    lower = path.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(path)
    try:
        return _read_xls(path)
    except xlrd.XLRDError:
        # Some ".xls" files are really .xlsx files with the wrong extension
        return _read_xlsx(path)
