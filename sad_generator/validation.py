"""Pre-flight checks on a shipment before the SAD is built.

Everything here is a *warning*: the SAD is still generated, but the user sees
what Customs (or ASYCUDA's own import validation) is likely to reject, with the
SAD box number so it can be found quickly. ``check_shipment`` returns structured
issues; ``validate`` flattens them to the plain strings the UI and CLI show.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .utils import normalize_hs_code, parse_number

ERROR, WARNING = "error", "warning"

# ISO 3166-1 alpha-2 — ASYCUDA's country boxes (15 export, 34 origin) use these codes.
ISO_COUNTRIES = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO
JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR
MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO
RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV
TW TZ UA UG US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())

INCOTERMS = frozenset("EXW FCA FAS FOB CFR CIF CPT CIP DAP DPU DDP DAT DAF DES DEQ DDU".split())

# Relative tolerance when comparing sums of lines with a declared total.
TOLERANCE = 0.01


@dataclass(frozen=True)
class Issue:
    severity: str          # "error" | "warning"
    message: str
    item: int | None = None    # 1-based item number, None for header-level issues
    field: str = ""            # key of the offending field

    def __str__(self) -> str:
        return self.message


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _is_iso(value) -> bool:
    return str(value or "").strip().upper() in ISO_COUNTRIES


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.05, TOLERANCE * max(abs(a), abs(b)))


def _check_general(g: dict, items: list[dict], out: list[Issue]) -> None:
    def add(sev, msg, field=""):
        out.append(Issue(sev, msg, None, field))

    if not str(g.get("bl_number") or "").strip():
        add(WARNING, "BL number is empty (box 40).", "bl_number")

    export = _first(g, "country_of_export")
    if export and not _is_iso(export):
        add(WARNING, f"Country of export “{export}” is not a 2-letter country code (box 15).", "country_of_export")

    currency = str(_first(g, "invoice_currency") or "")
    if currency and not (len(currency) == 3 and currency.isalpha()):
        add(ERROR, f"Invoice currency “{currency}” must be a 3-letter code such as USD (box 22).", "invoice_currency")

    terms = str(_first(g, "delivery_terms") or "").strip().upper()
    if terms and terms not in INCOTERMS:
        add(WARNING, f"Delivery terms “{terms}” is not a recognised Incoterm (box 20).", "delivery_terms")

    # Declared totals against the item lines
    prices = [parse_number(i.get("item_price")) for i in items]
    if prices and all(p is not None for p in prices):
        declared = parse_number(g.get("invoice_amount"))
        total = sum(prices)
        if declared and not _close(declared, total):
            add(WARNING, f"Items add up to {total:,.2f} but the invoice total is {declared:,.2f} (boxes 42 / 22).",
                "invoice_amount")

    declared_pkgs = parse_number(g.get("total_packages"))
    pkgs = [parse_number(_first(i, "no_packages", "no_of_packages")) for i in items]
    if declared_pkgs and any(p is not None for p in pkgs):
        got = sum(p for p in pkgs if p is not None)
        if int(got) != int(declared_pkgs):
            add(WARNING, f"Items have {int(got):,} packages but the total says {int(declared_pkgs):,} (box 6).",
                "total_packages")


def _check_item(idx: int, it: dict, out: list[Issue]) -> None:
    def add(sev, msg, field=""):
        out.append(Issue(sev, f"Item {idx}: {msg}", idx, field))

    if not str(it.get("description") or it.get("commercial_description") or "").strip():
        add(WARNING, "description is empty (box 31).", "description")

    # Price
    raw_price = it.get("item_price")
    if raw_price in (None, ""):
        add(WARNING, "item price is empty (box 42).", "item_price")
    else:
        price = parse_number(raw_price)
        if price is None:
            add(ERROR, f"item price “{raw_price}” is not a number (box 42).", "item_price")
        elif price < 0:
            add(WARNING, "item price is negative (box 42).", "item_price")
        elif price == 0:
            add(WARNING, "item price is zero (box 42).", "item_price")

    # HS code
    hs = normalize_hs_code(it.get("hs_code"))
    if not hs:
        add(WARNING, "HS code is missing (box 33).", "hs_code")
    elif not hs.isdigit():
        add(WARNING, f"HS code “{hs}” has non-digit characters (box 33).", "hs_code")
    elif len(hs) not in (6, 8, 10):
        add(WARNING, f"HS code {hs} has {len(hs)} digits — expected 6, 8 or 10 (box 33).", "hs_code")
    elif len(hs) < 8:
        add(WARNING, f"HS code {hs} is only 6 digits; Maldives Customs needs the full national code (box 33).",
            "hs_code")

    # Country of origin
    origin = _first(it, "country_origin", "country_of_origin")
    if origin and not _is_iso(origin):
        add(WARNING, f"country of origin “{origin}” is not a 2-letter country code (box 34).", "country_origin")

    # Quantities
    for label, keys, box in (("gross mass", ("gross_mass",), "35"), ("supplementary quantity",
                                                                      ("supp_units", "supplementary_units"), "41")):
        raw = _first(it, *keys)
        if raw is None:
            continue
        n = parse_number(raw)
        if n is None:
            add(ERROR, f"{label} “{raw}” is not a number (box {box}).", keys[0])
        elif n < 0:
            add(WARNING, f"{label} is negative (box {box}).", keys[0])

    pk = _first(it, "no_packages", "no_of_packages")
    if pk is not None:
        n = parse_number(pk)
        if n is None:
            add(ERROR, f"number of packages “{pk}” is not a number (box 31).", "no_packages")
        elif n < 0 or n != int(n):
            add(WARNING, f"number of packages {pk} should be a whole, non-negative number (box 31).", "no_packages")


def check_shipment(data: dict) -> list[Issue]:
    """All pre-flight issues for ``{"general": ..., "items": [...]}``."""
    g = data.get("general") or {}
    items = data.get("items") or []
    issues: list[Issue] = []
    _check_general(g, items, issues)
    for idx, it in enumerate(items, start=1):
        _check_item(idx, it, issues)

    # Repeated lines are usually a copy/paste slip
    def key(it):
        return (normalize_hs_code(it.get("hs_code")),
                str(it.get("description") or "").strip().lower(),
                parse_number(it.get("item_price")), parse_number(it.get("gross_mass")))

    keys = [key(it) for it in items]
    counts = Counter(k for k in keys if k[1])     # ignore lines without a description
    for idx, k in enumerate(keys, start=1):
        if counts.get(k, 0) > 1 and keys.index(k) + 1 != idx:
            first = keys.index(k) + 1
            issues.append(Issue(WARNING, f"Item {idx}: looks like a duplicate of item {first}.", idx, "description"))
    return issues


def validate(data: dict) -> list[str]:
    """The issues as plain strings (what the UI and CLI show next to the result)."""
    return [i.message for i in check_shipment(data)]
