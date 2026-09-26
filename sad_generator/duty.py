"""Customs-duty calculation."""

from __future__ import annotations

from .utils import parse_number, parse_rate

PREFERENTIAL_KEYS = {"general": "duty_rate", "safta": "safta_rate", "cmfta": "cmfta_rate"}


def check_preferential(preferential: str) -> str:
    p = (preferential or "general").strip().lower()
    if p not in PREFERENTIAL_KEYS:
        raise ValueError(f"preferential must be one of {sorted(PREFERENTIAL_KEYS)}, got {preferential!r}")
    return p


def calculate_item_duty(item: dict, preferential: str = "general") -> dict:
    """Duty for one item: ``item_price × rate / 100`` using the chosen tariff column.

    For SAFTA/CMFTA, falls back to the general rate when the preferential
    rate isn't published for that code.
    """
    preferential = check_preferential(preferential)
    rate = parse_rate(item.get(PREFERENTIAL_KEYS[preferential]))
    if rate is None and preferential != "general":
        rate = parse_rate(item.get("duty_rate"))
    price = parse_number(item.get("item_price"), 0.0)
    if rate is None:
        return {"duty_rate": None, "duty_amount": 0.0, "total_with_duty": round(price, 2), "preferential": preferential}
    duty_amount = round(price * rate / 100.0, 2)
    return {
        "duty_rate": rate,
        "duty_amount": duty_amount,
        "total_with_duty": round(price + duty_amount, 2),
        "preferential": preferential,
    }


def build_items_preview_and_duty(
    items: list[dict],
    preferential: str = "general",
    currency: str = "USD",
    preview_limit: int = 500,
) -> tuple[list[dict], dict]:
    """Per-item preview rows (first ``preview_limit``) and totals over *all* items."""
    preview: list[dict] = []
    total_value = total_duty = total_with = 0.0
    with_rate = missing_rate = 0
    for idx, it in enumerate(items):
        d = calculate_item_duty(it, preferential)
        price = parse_number(it.get("item_price"), 0.0)
        total_value += price
        total_duty += d["duty_amount"]
        total_with += d["total_with_duty"]
        if d["duty_rate"] is None:
            missing_rate += 1
        else:
            with_rate += 1
        if idx < preview_limit:
            preview.append({
                "hs_code": str(it.get("hs_code", "")),
                "description": str(it.get("description", it.get("commercial_description", "")))[:80],
                "looked_up": bool(it.get("_hs_looked_up")),
                "candidates": (it.get("_hs_candidates") or [])[:3],
                "item_price": price,
                "duty_rate": d["duty_rate"],
                "duty_amount": d["duty_amount"],
                "total_with_duty": d["total_with_duty"],
                "hs_unit": it.get("hs_unit", ""),
                "safta_rate": it.get("safta_rate"),
                "cmfta_rate": it.get("cmfta_rate"),
                "country_origin": str(it.get("country_origin") or it.get("country_of_origin") or "").upper(),
                "gross_mass": parse_number(it.get("gross_mass"), None),
                "no_packages": parse_number(it.get("no_packages", it.get("no_of_packages")), None),
                "brand": str(it.get("brand") or ""),
            })
    summary = {
        "preferential": preferential,
        "total_item_value": round(total_value, 2),
        "total_duty": round(total_duty, 2),
        "total_with_duty": round(total_with, 2),
        "items_with_duty": with_rate,
        "items_missing_duty": missing_rate,
        "currency": currency or "USD",
    }
    return preview, summary
