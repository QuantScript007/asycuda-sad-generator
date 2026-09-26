"""Fill the official ASYCUDA SAD model workbook (``templates/SAD_MODEL.xls``).

This is the file users download and import into ASYCUDA. The model is copied
cell-for-cell: its formatting, hidden currency columns, dropdown lists and the
field-hint comments all stay exactly as in the original — only the values
change. Replace the model by setting ``SAD_MODEL_PATH`` to another .xls with
the same layout.
"""

from __future__ import annotations

import os
from pathlib import Path

from .utils import normalize_hs_code, parse_number
from .xls_template import XlsTemplate

DEFAULT_MODEL = Path(__file__).resolve().parent / "templates" / "SAD_MODEL.xls"

GENERAL_SHEET, ITEMS_SHEET = "General Segment", "Items"
FIRST_ITEM_ROW = 3          # row 4 in Excel
VALUE_COL, EXTRA_COL = 2, 3  # columns C and D of the General Segment

# General Segment: row -> (value key, default, kind, extra key, extra default, extra kind)
#   kind: "text" | "num" | "int"; extra (column D) is usually a currency.
GENERAL_ROWS = {
    1: ("customs_office", "00MP", "text", None, None, None),
    2: ("manifest_no", "", "text", None, None, None),
    3: ("office_entry_exit", None, "text", None, None, None),   # defaults to the clearance office
    4: ("decl_type", "IM", "text", "decl_subtype", 4, "num"),
    5: ("procedure", "4000", "text", "procedure_add", "000", "text"),
    6: ("exporter", "", "text", None, None, None),
    7: ("consignee_code", "C8888", "text", None, None, None),
    8: ("declarant_code", "C8888", "text", None, None, None),
    9: ("sector", "", "text", None, None, None),
    10: ("financial", "", "text", None, None, None),
    11: ("country_of_export", "", "text", None, None, None),
    12: ("vessel_name", "", "text", None, None, None),
    13: ("delivery_terms", "CIF", "text", None, None, None),
    14: ("invoice_amount", 0, "num", "invoice_currency", "USD", "currency"),
    15: ("internal_freight", "", "num", None, None, None),
    16: ("external_freight", "", "num", "freight_currency", "USD", "currency"),
    17: ("insurance", "", "num", "insurance_currency", "USD", "currency"),
    18: ("other_costs", "", "num", "other_costs_currency", "USD", "currency"),
    19: ("deductions", "", "num", None, None, None),
    20: ("location_goods", "", "text", None, None, None),
    21: ("working_mode", 0, "num", None, None, None),
    22: ("prepayment_code", "", "text", None, None, None),
    23: ("bl_number", "", "text", None, None, None),
    24: ("mode_transport", "1", "text", None, None, None),
    25: ("place_discharge", "", "text", None, None, None),
    26: ("carrier_nationality", "MV", "text", None, None, None),
    27: ("trading_country", "", "text", None, None, None),
    28: ("total_packages", 0, "int", None, None, None),
}

# Alternative spellings accepted for general keys
GENERAL_ALIASES = {
    "location_goods": ("location_of_goods",),
    "prepayment_code": ("pre_payment_code",),
    "mode_transport": ("mode_of_transport",),
    "place_discharge": ("place_of_discharge",),
}

# Items sheet: column -> (item key(s), kind, max length)
ITEM_COLUMNS = {
    1: (("hs_code",), "hs", None),
    2: (("supp_units", "supplementary_units"), "num", None),
    3: (("country_origin", "country_of_origin"), "text", None),
    4: (("gross_mass",), "num", None),
    5: (("preference",), "text", None),
    6: (("item_price",), "num", None),
    19: (("unit_nos",), "num", None),
    20: (("description", "commercial_description"), "text", 49),
    21: (("packing1", "packing_1st"), "num", None),
    22: (("packing_code1", "packing_code_1"), "text", 5),
    23: (("packing3", "packing_3rd"), "num", None),
    24: (("packing_code2", "packing_code_2"), "text", 5),
    25: (("brand",), "text", 24),
    26: (("model",), "text", 24),
    27: (("size",), "text", 24),
    28: (("package_code",), "text", None),
    29: (("no_packages", "no_of_packages"), "int", None),
}

# Item-level costs (hidden columns H–Q; used by ASYCUDA only in some working modes):
# amount column -> (item keys, currency item key, general currency key)
ITEM_COSTS = {
    7: (("int_freight", "internal_freight"), "int_freight_currency", "invoice_currency"),
    9: (("ext_freight", "external_freight"), "ext_freight_currency", "freight_currency"),
    11: (("insurance",), "insurance_currency", "insurance_currency"),
    13: (("other_costs",), "other_costs_currency", "other_costs_currency"),
    15: (("deductions",), "deductions_currency", "invoice_currency"),
}

FIELD_NAMES = {20: "description", 22: "packing code 1", 24: "packing code 2", 25: "brand", 26: "model", 27: "size"}


def model_path() -> Path:
    return Path(os.environ.get("SAD_MODEL_PATH") or DEFAULT_MODEL)


def _first(d: dict, keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
        v = d.get(k.replace("_", " "))
        if v not in (None, ""):
            return v
    return default


def _convert(value, kind: str):
    if value in (None, ""):
        return None
    if kind == "hs":
        return normalize_hs_code(value) or None
    if kind in ("num", "int"):
        n = parse_number(value, None)
        if n is None:
            return str(value)
        return float(int(round(n))) if kind == "int" else n
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return str(value).strip()


def load_model() -> XlsTemplate:
    return XlsTemplate(model_path().read_bytes())


def blank_model_bytes() -> bytes:
    """The model with its sample values removed — ready to fill by hand."""
    tpl = load_model()
    tpl.clear_values(GENERAL_SHEET, range(1, 29), range(VALUE_COL, EXTRA_COL + 1))
    tpl.clear_values(ITEMS_SHEET, range(FIRST_ITEM_ROW, tpl.row_count(ITEMS_SHEET)))
    return tpl.to_bytes()


def create_sad_model_workbook(data: dict) -> tuple[bytes, list[str]]:
    """Fill the SAD model with ``{"general": ..., "items": [...]}``.

    Returns the .xls bytes and a list of warnings (e.g. text that had to be
    shortened to ASYCUDA's field limits).
    """
    g = data.get("general") or {}
    items = data.get("items") or []
    warnings: list[str] = []
    tpl = load_model()

    # ── General Segment ──
    tpl.clear_values(GENERAL_SHEET, range(1, 29), range(VALUE_COL, EXTRA_COL + 1))
    for row, (key, default, kind, extra_key, extra_default, extra_kind) in GENERAL_ROWS.items():
        keys = (key, *GENERAL_ALIASES.get(key, ()))
        if key == "office_entry_exit":
            default = _first(g, ("customs_office",), "00MP")
        value = _convert(_first(g, keys, default), kind)
        tpl.set(GENERAL_SHEET, row, VALUE_COL, value)
        if extra_key:
            if extra_kind == "currency":
                cur = _first(g, (extra_key,), extra_default) if value not in (None, "") else None
                tpl.set(GENERAL_SHEET, row, EXTRA_COL, _convert(cur, "text"))
            else:
                tpl.set(GENERAL_SHEET, row, EXTRA_COL, _convert(_first(g, (extra_key,), extra_default), extra_kind))

    # ── Items ──
    tpl.clear_values(ITEMS_SHEET, range(FIRST_ITEM_ROW, tpl.row_count(ITEMS_SHEET)))
    for idx, it in enumerate(items, start=1):
        r = FIRST_ITEM_ROW + idx - 1
        tpl.set(ITEMS_SHEET, r, 0, float(idx), style_row=FIRST_ITEM_ROW)
        for col, (keys, kind, max_len) in ITEM_COLUMNS.items():
            value = _convert(_first(it, keys), kind)
            if max_len and isinstance(value, str) and len(value) > max_len:
                warnings.append(
                    f"Item {idx}: {FIELD_NAMES.get(col, keys[0])} shortened to {max_len} characters "
                    f"(ASYCUDA limit): “{value[:max_len]}”"
                )
                value = value[:max_len]
            tpl.set(ITEMS_SHEET, r, col, value, style_row=FIRST_ITEM_ROW)
        for col, (keys, cur_key, general_cur_key) in ITEM_COSTS.items():
            amount = _convert(_first(it, keys), "num")
            tpl.set(ITEMS_SHEET, r, col, amount, style_row=FIRST_ITEM_ROW)
            cur = None
            if amount not in (None, ""):
                cur = _first(it, (cur_key,)) or _first(g, (general_cur_key,), "USD")
            tpl.set(ITEMS_SHEET, r, col + 1, _convert(cur, "text"), style_row=FIRST_ITEM_ROW)
    return tpl.to_bytes(), warnings
