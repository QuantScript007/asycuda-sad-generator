"""HS code and tariff lookup against the Maldives Customs online tariff.

Improvements over the original single-file version:

* one HTML parser shared by description search and exact-code lookup;
* an in-memory TTL cache, so the same code/description is fetched once;
* a concurrency limit, so a 200-line invoice doesn't fire 200 requests at once;
* one retry on network errors / 5xx responses.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from bs4 import BeautifulSoup

from . import config
from .utils import is_valid_hs, normalize_hs_code, parse_rate

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": config.HS_SEARCH_URL,
}

_cache: dict[str, tuple[float, list[dict]]] = {}
_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def clear_cache() -> None:
    _cache.clear()


def _get_semaphore() -> asyncio.Semaphore:
    """A semaphore bound to the running loop (tests/CLI may use several loops)."""
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(max(1, config.HS_MAX_CONCURRENCY))
        _semaphore_loop = loop
    return _semaphore


def parse_tariff_rows(html: str) -> list[dict]:
    """Extract tariff rows from the customs search results page.

    Column layout: 0=Code, 1=Description, 2=Unit, 3=Rate%, 4=Specific rate,
    5=SAFTA%, 6=SAFTA specific, 7=CMFTA%, 8=CMFTA specific, 9=Details.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        code = cells[0].get_text(strip=True).replace(" ", "")
        if len(code) < 8 or not code.isdigit() or code in seen:
            continue
        seen.add(code)

        def cell(i: int, cells=cells) -> str:
            return cells[i].get_text(strip=True) if len(cells) > i else ""

        rows.append({
            "hs_code": code,
            "description": cell(1),
            "hs_unit": cell(2),
            "duty_rate": parse_rate(cell(3)),
            "safta_rate": parse_rate(cell(5)),
            "cmfta_rate": parse_rate(cell(7)),
        })
    return rows


async def _search(term: str) -> list[dict]:
    """Run one search against the tariff site (cached, rate-limited, retried)."""
    key = term.strip().lower()
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < config.HS_CACHE_TTL:
        return hit[1]

    attempts = max(0, config.HS_RETRIES) + 1
    async with _get_semaphore():
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=config.HS_TIMEOUT) as client:
                    r = await client.get(config.HS_SEARCH_URL, params={"hsSearchIn": term}, headers=_HEADERS)
                if r.status_code >= 500 and attempt + 1 < attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if r.status_code != 200:
                    log.warning("HS search '%s' returned HTTP %s", term[:40], r.status_code)
                    return []
                rows = parse_tariff_rows(r.text)
                _cache[key] = (now, rows)
                return rows
            except httpx.HTTPError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                log.warning("HS search failed for '%s': %s", term[:40], exc)
                return []
    return []


async def lookup_hs_candidates(description: str, limit: int = 5) -> list[dict]:
    """Top HS-code matches (with duty/SAFTA/CMFTA rates) for a goods description."""
    description = (description or "").strip()
    if not description:
        return []
    return (await _search(description))[:limit]


async def lookup_hs_tariff(hs_code) -> dict | None:
    """Full tariff details for one exact HS code, or ``None`` if not found."""
    code = normalize_hs_code(hs_code)
    if not is_valid_hs(code):
        return None
    for row in await _search(code):
        if row["hs_code"] == code:
            return row
    return None


def _apply_tariff(item: dict, t: dict) -> None:
    """Copy tariff data onto an item. A duty rate the user supplied is kept."""
    if "duty_rate" not in item:
        item["duty_rate"] = t.get("duty_rate")
    for key in ("safta_rate", "cmfta_rate"):
        if item.get(key) is None:
            item[key] = t.get(key)
    if not item.get("hs_unit"):
        item["hs_unit"] = t.get("hs_unit", "")


async def enrich_items_hs_codes(items: list[dict], lookup: bool = True) -> list[dict]:
    """Fill in missing HS codes (by description) and duty rates (by HS code).

    Items are copied, never mutated. A duty rate already present on the item
    (e.g. typed into the manual form) is kept; everything else is fetched.
    With ``lookup=False`` nothing is fetched — useful offline.
    """
    enriched = [dict(it) for it in items]
    for it in enriched:
        it["hs_code"] = normalize_hs_code(it.get("hs_code"))
        for key in ("duty_rate", "safta_rate", "cmfta_rate"):
            rate = parse_rate(it.get(key))
            if rate is None:
                it.pop(key, None)
            else:
                it[key] = rate
        # Values computed by the browser are recalculated server-side
        it.pop("duty_amount", None)
        it.pop("total_with_duty", None)
    if not lookup:
        return enriched

    # Pass 1 — resolve missing HS codes from the description
    need_hs = [
        i for i, it in enumerate(enriched)
        if not it["hs_code"] and str(it.get("description") or it.get("commercial_description") or "").strip()
    ]
    results = await asyncio.gather(*(
        lookup_hs_candidates(str(enriched[i].get("description") or enriched[i].get("commercial_description")))
        for i in need_hs
    ))
    for i, candidates in zip(need_hs, results):
        it = enriched[i]
        it["_hs_looked_up"] = True
        it["_hs_candidates"] = candidates
        if candidates:
            top = candidates[0]
            it["hs_code"] = top["hs_code"]
            if top.get("duty_rate") is not None:
                _apply_tariff(it, top)
            log.info("[HS] '%s' -> %s (duty=%s%%)", str(it.get("description", ""))[:40], top["hs_code"], top.get("duty_rate"))

    # Pass 2 — fetch duty rates for items that have a code but no rate
    # (also when only the preferential SAFTA/CMFTA rates are missing — the
    # request is usually already cached from the manual form's live lookup)
    need_tariff = [
        i for i, it in enumerate(enriched)
        if is_valid_hs(it["hs_code"])
        and ("duty_rate" not in it or (it.get("safta_rate") is None and it.get("cmfta_rate") is None))
    ]
    tariffs = await asyncio.gather(*(lookup_hs_tariff(enriched[i]["hs_code"]) for i in need_tariff))
    for i, t in zip(need_tariff, tariffs):
        if t:
            _apply_tariff(enriched[i], t)
            log.info("[TARIFF] %s -> duty=%s%%", enriched[i]["hs_code"], t.get("duty_rate"))
    return enriched
