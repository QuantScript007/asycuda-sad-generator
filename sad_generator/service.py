"""The generate pipeline shared by the web API and the command line."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config
from .duty import build_items_preview_and_duty, check_preferential
from .hs_lookup import enrich_items_hs_codes
from .sad_builder import create_sad_workbook
from .utils import normalize_hs_code, safe_filename_part

log = logging.getLogger(__name__)


@dataclass
class GenerateResult:
    general: dict
    items: list[dict]
    output_path: Path
    hs_auto_filled: int
    items_preview: list[dict] = field(default_factory=list)
    duty_summary: dict = field(default_factory=dict)

    def to_response(self) -> dict:
        g = self.general
        return {
            "bl_number": str(g.get("bl_number", "N/A")),
            "vessel": str(g.get("vessel_name", "N/A")),
            "consignee": str(g.get("consignee_code", "N/A")),
            "country_of_export": str(g.get("country_of_export", "N/A")),
            "delivery_terms": str(g.get("delivery_terms", "N/A")),
            "item_count": len(self.items),
            "hs_auto_filled": self.hs_auto_filled,
            "download_url": f"/output/{self.output_path.name}",
            "output_file": str(self.output_path),
            "items_preview": self.items_preview,
            "duty_summary": self.duty_summary,
        }


def validate(data: dict) -> list[str]:
    """Non-fatal warnings about the input, shown to the user alongside the result."""
    warnings: list[str] = []
    g = data.get("general", {})
    if not g.get("bl_number"):
        warnings.append("BL number is empty (box 40).")
    for idx, it in enumerate(data.get("items", []), start=1):
        if not str(it.get("description") or it.get("commercial_description") or "").strip():
            warnings.append(f"Item {idx}: description is empty (box 31).")
        if it.get("item_price") in (None, ""):
            warnings.append(f"Item {idx}: item price is empty (box 42).")
    return warnings


def output_name(general: dict, now: datetime | None = None) -> str:
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"SAD_{safe_filename_part(general.get('bl_number'), 'manual')}_{ts}.xls"


async def generate(
    data: dict,
    *,
    preferential: str = "general",
    lookup: bool = True,
    output_dir: Path | None = None,
    output_path: Path | None = None,
) -> GenerateResult:
    """Enrich items with HS codes / duty rates, build the SAD and save it."""
    preferential = check_preferential(preferential)
    general = dict(data.get("general") or {})
    items = [dict(i) for i in (data.get("items") or [])]
    if not items:
        raise ValueError("No items found.")

    log.info("Enriching %d item(s) (lookup=%s)", len(items), lookup)
    items = await enrich_items_hs_codes(items, lookup=lookup)
    for it in items:
        it["hs_code"] = normalize_hs_code(it.get("hs_code"))

    sad_bytes = create_sad_workbook({"general": general, "items": items}, preferential)

    if output_path is None:
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / output_name(general)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(sad_bytes)
    log.info("Saved %s", output_path)

    preview, summary = build_items_preview_and_duty(
        items, preferential, currency=str(general.get("invoice_currency") or "USD")
    )
    summary["warnings"] = validate({"general": general, "items": items})
    return GenerateResult(
        general=general,
        items=items,
        output_path=output_path,
        hs_auto_filled=sum(1 for i in items if i.get("_hs_looked_up") and i.get("hs_code")),
        items_preview=preview,
        duty_summary=summary,
    )
