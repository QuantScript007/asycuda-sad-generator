"""MVR exchange rates from Maldives Customs (https://customs.gov.mv/eServices/exchangeRate).

Customs publishes the rate (MVR per unit of foreign currency) used to value
imports. The page layout isn't documented, so the parser is deliberately
tolerant: it looks at every table row for a 3-letter currency code and takes
the rate from the numeric cells in that row. Results are cached; if the site
can't be reached, a rate typed by the user (``exchange_rate`` in the
declaration) or the fallback table below is used, and the result says so.
"""

from __future__ import annotations

import logging
import re
import time

import httpx
from bs4 import BeautifulSoup

from . import config
from .utils import parse_number

log = logging.getLogger(__name__)

# Used only when Customs can't be reached and no rate was given.
# MVR is pegged to USD; 15.42 is the long-standing customs valuation rate.
FALLBACK_RATES = {"MVR": 1.0, "USD": 15.42}

_CODE_RE = re.compile(r"^[A-Z]{3}$")
_cache: dict = {"at": 0.0, "rates": {}}


def parse_exchange_table(html: str) -> dict[str, float]:
    """Extract ``{currency code: MVR per unit}`` from the Customs exchange-rate page."""
    soup = BeautifulSoup(html, "html.parser")
    rates: dict[str, float] = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        code = next((c.upper() for c in cells if _CODE_RE.match(c.strip().upper()) and c.strip().isalpha()), None)
        if not code or code in rates:
            continue
        # e.g. "USD | US Dollar | 15.42" or "USD | 1 | 15.42"; a unit column ("100 JPY") divides the rate
        numbers = [parse_number(c.replace(",", ""), None) for c in cells]
        numbers = [n for n in numbers if n is not None and n > 0]
        if not numbers:
            continue
        rate = numbers[-1]
        unit = numbers[0] if len(numbers) >= 2 and numbers[0] in (10, 100, 1000) else 1
        rates[code] = round(rate / unit, 6)
    rates.setdefault("MVR", 1.0)
    return rates


async def fetch_rates(force: bool = False) -> dict[str, float]:
    """Current rates from Customs (cached for ``SAD_FX_CACHE_TTL`` seconds)."""
    now = time.monotonic()
    if not force and _cache["rates"] and now - _cache["at"] < config.FX_CACHE_TTL:
        return _cache["rates"]
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=config.HS_TIMEOUT) as client:
            r = await client.get(config.FX_URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if r.status_code != 200:
            log.warning("Exchange-rate page returned HTTP %s", r.status_code)
            return {}
        rates = parse_exchange_table(r.text)
        if len(rates) > 1:
            _cache.update(at=now, rates=rates)
        return rates
    except httpx.HTTPError as exc:
        log.warning("Exchange-rate lookup failed: %s", exc)
        return {}


def clear_cache() -> None:
    _cache.update(at=0.0, rates={})


async def resolve_rate(currency: str, override=None, lookup: bool = True) -> dict:
    """Pick the MVR rate for ``currency``.

    Order: a rate the user typed → Customs website → fallback table.
    Returns ``{"currency", "rate", "source"}`` where source is
    ``"manual" | "customs" | "fallback" | "missing"``.
    """
    cur = (currency or "USD").strip().upper()
    manual = parse_number(override, None)
    if manual and manual > 0:
        return {"currency": cur, "rate": manual, "source": "manual"}
    if cur == "MVR":
        return {"currency": cur, "rate": 1.0, "source": "customs"}
    if lookup:
        rates = await fetch_rates()
        if cur in rates:
            return {"currency": cur, "rate": rates[cur], "source": "customs"}
    if cur in FALLBACK_RATES:
        return {"currency": cur, "rate": FALLBACK_RATES[cur], "source": "fallback"}
    return {"currency": cur, "rate": None, "source": "missing"}
