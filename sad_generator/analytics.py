"""Shipment analytics shown on the results dashboard and file preview."""

from __future__ import annotations

from collections import defaultdict

from .duty import calculate_item_duty
from .utils import normalize_hs_code, parse_number

# Short names for the 97 chapters of the Harmonized System.
HS_CHAPTERS = {
    "01": "Live animals", "02": "Meat", "03": "Fish & seafood", "04": "Dairy, eggs, honey",
    "05": "Other animal products", "06": "Plants & flowers", "07": "Vegetables", "08": "Fruit & nuts",
    "09": "Coffee, tea, spices", "10": "Cereals", "11": "Milling products", "12": "Oil seeds",
    "13": "Gums & resins", "14": "Plaiting materials", "15": "Fats & oils", "16": "Meat & fish preparations",
    "17": "Sugars", "18": "Cocoa", "19": "Cereal & bakery products", "20": "Vegetable & fruit preparations",
    "21": "Misc. food preparations", "22": "Beverages", "23": "Food residues & animal feed", "24": "Tobacco",
    "25": "Salt, stone, cement", "26": "Ores", "27": "Mineral fuels & oils", "28": "Inorganic chemicals",
    "29": "Organic chemicals", "30": "Pharmaceuticals", "31": "Fertilisers", "32": "Paints & dyes",
    "33": "Cosmetics & perfumes", "34": "Soap & detergents", "35": "Glues & enzymes", "36": "Explosives & matches",
    "37": "Photographic goods", "38": "Misc. chemicals", "39": "Plastics", "40": "Rubber",
    "41": "Hides & leather", "42": "Leather goods & bags", "43": "Furskins", "44": "Wood",
    "45": "Cork", "46": "Basketware", "47": "Pulp", "48": "Paper & paperboard",
    "49": "Printed matter", "50": "Silk", "51": "Wool", "52": "Cotton",
    "53": "Other vegetable fibres", "54": "Man-made filaments", "55": "Man-made staple fibres", "56": "Wadding & rope",
    "57": "Carpets", "58": "Special woven fabrics", "59": "Coated textiles", "60": "Knitted fabrics",
    "61": "Knitted apparel", "62": "Woven apparel", "63": "Other textile articles", "64": "Footwear",
    "65": "Headgear", "66": "Umbrellas", "67": "Feathers & artificial flowers", "68": "Stone & cement articles",
    "69": "Ceramics", "70": "Glass", "71": "Jewellery & precious metals", "72": "Iron & steel",
    "73": "Iron & steel articles", "74": "Copper", "75": "Nickel", "76": "Aluminium",
    "78": "Lead", "79": "Zinc", "80": "Tin", "81": "Other base metals",
    "82": "Tools & cutlery", "83": "Misc. metal articles", "84": "Machinery & appliances", "85": "Electrical equipment",
    "86": "Railway equipment", "87": "Vehicles", "88": "Aircraft", "89": "Ships & boats",
    "90": "Optical & medical instruments", "91": "Clocks & watches", "92": "Musical instruments", "93": "Arms",
    "94": "Furniture & lighting", "95": "Toys & sports goods", "96": "Misc. manufactured articles", "97": "Art & antiques",
    "98": "Special provisions", "99": "Special provisions",
}

RATE_BANDS = [("0%", 0, 0), ("0–10%", 0, 10), ("10–20%", 10, 20), ("20–30%", 20, 30), (">30%", 30, 10**9)]


def _band(rate: float | None) -> str:
    if rate is None:
        return "Unknown"
    if rate == 0:
        return "0%"
    for label, lo, hi in RATE_BANDS[1:]:
        if lo < rate <= hi:
            return label
    return ">30%"


def _group_rows(groups: dict, total_value: float, limit: int) -> list[dict]:
    rows = sorted(groups.values(), key=lambda g: (-g["value"], g["key"]))
    for r in rows:
        r["value"] = round(r["value"], 2)
        r["duty"] = round(r["duty"], 2)
        r["share"] = round(100 * r["value"] / total_value, 1) if total_value else 0.0
    if len(rows) > limit:
        rest = rows[limit - 1:]
        rows = rows[: limit - 1] + [{
            "key": "other", "label": f"Other ({len(rest)})",
            "items": sum(r["items"] for r in rest),
            "value": round(sum(r["value"] for r in rest), 2),
            "duty": round(sum(r["duty"] for r in rest), 2),
            "share": round(sum(r["share"] for r in rest), 1),
        }]
    return rows


def build_analytics(general: dict, items: list[dict], preferential: str = "general") -> dict:
    """Aggregate figures for the dashboard. Works with or without duty rates."""
    g = general or {}
    by_origin: dict = {}
    by_chapter: dict = {}
    bands: dict[str, int] = defaultdict(int)
    sources = {"manual": 0, "auto": 0, "missing": 0}
    duty_rows = []
    total_value = total_duty = total_mass = 0.0
    total_pkgs = 0

    for idx, it in enumerate(items, start=1):
        d = calculate_item_duty(it, preferential)
        value = parse_number(it.get("item_price"), 0.0)
        total_value += value
        total_duty += d["duty_amount"]
        total_mass += parse_number(it.get("gross_mass"), 0.0)
        total_pkgs += int(parse_number(it.get("no_packages", it.get("no_of_packages")), 0.0))
        bands[_band(d["duty_rate"])] += 1

        hs = normalize_hs_code(it.get("hs_code"))
        if not hs:
            sources["missing"] += 1
        elif it.get("_hs_looked_up"):
            sources["auto"] += 1
        else:
            sources["manual"] += 1

        origin = str(it.get("country_origin") or it.get("country_of_origin") or "").strip().upper() or "??"
        o = by_origin.setdefault(origin, {"key": origin, "label": origin, "items": 0, "value": 0.0, "duty": 0.0})
        o["items"] += 1
        o["value"] += value
        o["duty"] += d["duty_amount"]

        ch = hs[:2] if len(hs) >= 2 else "??"
        c = by_chapter.setdefault(ch, {
            "key": ch, "label": HS_CHAPTERS.get(ch, "Unclassified" if ch == "??" else f"Chapter {ch}"),
            "items": 0, "value": 0.0, "duty": 0.0,
        })
        c["items"] += 1
        c["value"] += value
        c["duty"] += d["duty_amount"]

        duty_rows.append({
            "index": idx, "hs_code": hs,
            "description": str(it.get("description") or it.get("commercial_description") or "")[:60],
            "value": round(value, 2), "duty_rate": d["duty_rate"], "duty": d["duty_amount"],
        })

    # Cost build-up (declaration-level figures from the header)
    invoice = parse_number(g.get("invoice_amount"), None) or None  # blank or 0 → not declared
    ext_freight = parse_number(g.get("external_freight"), 0.0)
    int_freight = parse_number(g.get("internal_freight"), 0.0)
    insurance = parse_number(g.get("insurance"), 0.0)
    other = parse_number(g.get("other_costs"), 0.0)
    deductions = parse_number(g.get("deductions"), 0.0)
    goods_value = invoice if invoice is not None else total_value
    cif = goods_value + ext_freight + int_freight + insurance + other - deductions

    diff = None if invoice is None else round(total_value - invoice, 2)
    reconciliation = {
        "declared_invoice": invoice,
        "sum_of_items": round(total_value, 2),
        "difference": diff,
        "matches": None if diff is None else abs(diff) < 0.01,
    }

    top_duty = sorted((r for r in duty_rows if r["duty"] > 0), key=lambda r: -r["duty"])[:5]
    rated = [r for r in duty_rows if r["duty_rate"] is not None]
    highest = max(rated, key=lambda r: r["duty_rate"]) if rated else None

    return {
        "totals": {
            "items": len(items),
            "item_value": round(total_value, 2),
            "duty": round(total_duty, 2),
            "effective_rate": round(100 * total_duty / total_value, 2) if total_value else 0.0,
            "gross_mass": round(total_mass, 3),
            "packages": total_pkgs,
            "declared_packages": int(parse_number(g.get("total_packages"), 0.0)) or None,
            "value_per_kg": round(total_value / total_mass, 2) if total_mass else None,
            "origins": len(by_origin),
            "chapters": len(by_chapter),
        },
        "cost_breakdown": {
            "goods": round(goods_value, 2),
            "external_freight": round(ext_freight, 2),
            "internal_freight": round(int_freight, 2),
            "insurance": round(insurance, 2),
            "other_costs": round(other, 2),
            "deductions": round(deductions, 2),
            "cif": round(cif, 2),
            "duty": round(total_duty, 2),
            "landed": round(cif + total_duty, 2),
        },
        "reconciliation": reconciliation,
        "by_origin": _group_rows(by_origin, total_value, 6),
        "by_chapter": _group_rows(by_chapter, total_value, 6),
        "rate_bands": [{"label": lbl, "count": bands.get(lbl, 0)} for lbl, *_ in RATE_BANDS]
        + [{"label": "Unknown", "count": bands.get("Unknown", 0)}],
        "hs_sources": sources,
        "top_duty_items": top_duty,
        "highest_rate_item": highest,
    }
