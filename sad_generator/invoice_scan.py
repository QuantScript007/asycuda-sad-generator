"""Read scanned invoices, packing lists and bills of lading into SAD form data.

Two ways in, one result:

* **Claude** (when an Anthropic API key is set) reads the page images or PDFs
  directly and returns the header and every line item as JSON.
* **Free text parsing** — the browser runs OCR (or takes a PDF's own text
  layer) and sends the text here; :func:`parse_invoice_text` picks out the
  header fields and the item rows.

Either way the result is mapped onto the generator's own field names
(``exporter``, ``bl_number``, ``item_price``, ``supp_units``…) so it can fill
the manual-entry form, and each item's HS code is then anchored to the real
Maldives Customs tariff by :func:`resolve_hs_codes`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re

import httpx

from . import config, hs_lookup
from .utils import normalize_hs_code

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PDF_TYPE = "application/pdf"


class ScanError(Exception):
    """A reading failure with a message fit to show the user."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ── Claude ───────────────────────────────────────────────────

SHAPE = """{"header":{"supplier_name":null,"supplier_address":null,"supplier_country":null,"consignee_name":null,
"invoice_no":null,"invoice_date":null,"currency":null,"invoice_total":null,"incoterm":null,"transport_mode":null,
"vessel_flight":null,"bl_awb_no":null,"port_of_loading":null,"port_of_discharge":null,"country_of_export":null,
"total_packages":null,"package_type":null,"gross_weight_kg":null,"net_weight_kg":null,"freight":null,
"insurance":null,"other_charges":null,"discount":null},
"items":[{"description":"","brand":null,"model":null,"hs_code":"","hs_confidence":"high|medium|low","origin":null,
"quantity":0,"unit":"PCS","unit_price":0,"total_price":0,"packages":null,"package_type":null,
"gross_weight_kg":null,"net_weight_kg":null}],
"notes":[]}"""

PROMPT = """You are preparing a Maldives Customs import declaration (ASYCUDA SAD) from the attached trade documents:
a commercial invoice, and possibly a packing list, proforma, delivery note, bill of lading or airway bill.
The attached files, in order: {files}

Read the document header and every invoice line item. Rules:
- Never invent values. Use null when a value is not on the documents or is illegible, and mention illegible parts in notes.
- Numbers are plain JSON numbers: no currency symbols, no thousands separators, keep the printed decimals.
- Weights in kilograms. If the documents use lb, convert and say so in notes.
- If a packing list is included, copy its package count, package kind, gross and net weight onto the matching
  invoice lines. Never create extra lines for packing-list rows.
- If weights are only given for the whole shipment, put them in the header and leave line weights null.
- quantity, unit and unit_price as printed; total_price is the line amount as printed.
- unit: short uppercase code (PCS, SET, KG, LTR, CTN, BOX, PR, M, DOZ, ROLL).
- description: the full commercial description including material, size and use. Put brand and model number in
  their own fields when shown.
- hs_code: the most specific Harmonized System code you can justify from the description, at least 6 digits,
  dotted like "8215.20" or "6302.60.10". hs_confidence: "high", "medium" or "low".
- origin and country fields: ISO 3166 alpha-2 codes (CN, SG, IN, AE ...).
- Do not put subtotal, tax, freight, insurance, handling or discount rows in items. Put freight, insurance,
  other charges and discount amounts in the header.
- transport_mode: Sea, Air, Road, Post or Courier. Dates as YYYY-MM-DD.
Reply with only JSON in exactly this shape:
{shape}"""


def _extract_json(text: str):
    """The JSON value in a model reply: the whole reply, a code fence, or the outermost braces."""
    for candidate in (
        text.strip(),
        (re.search(r"```(?:json)?\s*([\s\S]*?)```", text) or [None, None])[1],
        text[text.find("{"): text.rfind("}") + 1] if "{" in text else None,
    ):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            continue
    raise ScanError("Claude's answer couldn't be turned into lines. Try again, or scan fewer pages at once.")


async def read_with_claude(files: list[tuple[str, bytes, str]], api_key: str, model: str | None = None) -> dict:
    """Send the documents to Claude and return its raw JSON (Declaration Desk shape)."""
    content: list[dict] = []
    for name, data, media_type in files:
        b64 = base64.standard_b64encode(data).decode()
        if media_type == PDF_TYPE:
            content.append({"type": "document", "source": {"type": "base64", "media_type": PDF_TYPE, "data": b64},
                            "title": name})
        elif media_type in IMAGE_TYPES:
            content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
        else:
            raise ScanError(f"{name}: use PDF, JPG, PNG or WebP.", 415)
    names = ", ".join(f"{i}. {n}" for i, (n, _, _) in enumerate(files, 1))
    content.append({"type": "text", "text": PROMPT.format(files=names, shape=SHAPE)})

    body = {"model": model or config.SCAN_MODEL, "max_tokens": 16000, "messages": [{"role": "user", "content": content}]}
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=config.SCAN_TIMEOUT) as client:
            r = await client.post(ANTHROPIC_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise ScanError(f"Couldn't reach the Anthropic API ({exc.__class__.__name__}). Check your internet connection.") from exc

    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("message") or r.text[:300]
        except ValueError:
            detail = r.text[:300]
        if r.status_code == 401:
            msg = "The Anthropic API key was rejected. Check it in the Scan settings."
        elif "credit balance" in detail.lower():
            msg = "Your Anthropic account has no credit. Add credit under Billing at console.anthropic.com."
        elif r.status_code == 429:
            msg = "Too many requests right now. Wait a minute and try again."
        elif r.status_code == 529:
            msg = "Claude is busy right now. Wait a minute and try again."
        elif r.status_code == 404:
            msg = f"Model not found: {body['model']}. Change the model in the Scan settings."
        elif r.status_code == 413:
            msg = "The documents are too large for one request. Scan fewer pages at once."
        else:
            msg = "Claude couldn't read the documents."
        raise ScanError(f"{msg} (HTTP {r.status_code}: {detail})", 502 if r.status_code >= 500 else 400)

    text = "".join(block.get("text", "") for block in r.json().get("content", []) if block.get("type") == "text")
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise ScanError("Claude's answer wasn't in the expected shape. Try again.")
    return data


# ── Free text parsing (OCR / PDF text layer) ─────────────────

_UNIT_MAP = {
    "pc": "PCS", "pcs": "PCS", "piece": "PCS", "pieces": "PCS", "each": "PCS", "ea": "PCS", "unit": "PCS",
    "units": "PCS", "nos": "PCS", "set": "SET", "sets": "SET", "kg": "KG", "kgs": "KG", "l": "LTR", "ltr": "LTR",
    "ltrs": "LTR", "litre": "LTR", "litres": "LTR", "liter": "LTR", "liters": "LTR", "ctn": "CTN", "ctns": "CTN",
    "carton": "CTN", "cartons": "CTN", "box": "BOX", "boxes": "BOX", "bx": "BOX", "bxs": "BOX", "pr": "PR",
    "prs": "PR", "pair": "PR", "pairs": "PR", "m": "M", "mtr": "M", "mtrs": "M", "meter": "M", "meters": "M",
    "doz": "DOZ", "dozen": "DOZ", "roll": "ROLL", "rolls": "ROLL", "pkt": "PKT", "pkts": "PKT", "pack": "PKT",
    "packs": "PKT", "bag": "BAG", "bags": "BAG", "btl": "BTL", "btls": "BTL", "bottle": "BTL", "bottles": "BTL",
    "can": "CAN", "cans": "CAN", "drum": "DRUM", "drums": "DRUM", "tin": "TIN", "tins": "TIN", "case": "CASE",
    "cases": "CASE",
}
_SKIP_RE = re.compile(
    r"\b(sub\s*-?\s*total|grand\s*total|total|amount\s*due|balance|freight|insurance|tax|vat|gst|discount|"
    r"invoice\s*(no|number|date)|tel|phone|fax|e-?mail|page\s*\d|bank|account|a/c|swift|iban|payment|signature|"
    r"thank|deposit|shipping|handling)\b", re.I)
_CUR_RE = re.compile(r"^(usd|us\$|eur|sgd|aed|inr|cny|rmb|myr|gbp|thb|lkr|mvr|aud|jpy|\$|€|£)$", re.I)
_NUM_TOKEN_RE = re.compile(r"^[\d.,]*\d[\d.,]*$")
_CURRENCIES = r"USD|EUR|SGD|AED|INR|CNY|RMB|MYR|GBP|THB|LKR|AUD|JPY|MVR"


def parse_amount(s) -> float | None:
    """``'1,740.00'`` → 1740.0; European ``'1.740,00'`` / ``'12,50'`` are understood too."""
    s = re.sub(r"[^\d.,\-]", "", str(s or ""))
    if not re.search(r"\d", s):
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+,\d{1,2}", s) or re.fullmatch(r"-?\d+,\d{1,2}", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_item_line(line: str) -> dict | None:
    toks = line.split(" ")
    nums: list[float] = []
    unit = None
    i = len(toks) - 1
    while i >= 0:
        t = toks[i].strip("$€£")
        bare = t.rstrip(".:").lower()
        if _NUM_TOKEN_RE.match(t):
            n = parse_amount(t)
            if n is not None:
                nums.insert(0, n)
            i -= 1
            continue
        if unit is None and bare in _UNIT_MAP:
            unit = _UNIT_MAP[bare]
            i -= 1
            continue
        if _CUR_RE.match(bare) or not t:
            i -= 1
            continue
        break
    desc = toks[: i + 1]
    while desc and re.fullmatch(r"\d{1,3}[.)]?", desc[0]):
        desc.pop(0)
    description = " ".join(desc).strip(" -–:.")
    if len(nums) < 2 or not re.search(r"[a-z]{3}", description, re.I):
        return None

    total, prev = nums[-1], nums[:-1]
    qty = price = None
    for a, qa in enumerate(prev):
        for b, pb in enumerate(prev):
            if a != b and abs(qa * pb - total) <= max(0.02, total * 0.005):
                qty, price = (pb, qa) if (not qa.is_integer() and pb.is_integer()) else (qa, pb)
                break
        if qty is not None:
            break
    if qty is None:
        if len(prev) >= 2:
            qty, price = prev[-2], prev[-1]
        else:
            qty = prev[0]
            price = round(total / qty, 4) if qty else None
    return {"description": description, "quantity": qty, "unit": unit, "unit_price": price, "total_price": total}


def parse_invoice_text(text: str) -> dict:
    """Pick the header fields and item rows out of OCR or PDF text (Declaration Desk shape)."""
    items = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw.replace("|", " ").replace("¦", " ")).strip()
        if len(line) < 6 or _SKIP_RE.search(line):
            continue
        item = _parse_item_line(line)
        if item:
            items.append(item)

    flat = re.sub(r"[ \t]+", " ", text or "")

    # The letterhead: the first line that reads like a company name, and the line under it.
    supplier_name = supplier_address = None
    head = [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()[:8]]
    head = [ln for ln in head if ln]
    for idx, ln in enumerate(head):
        if (len(re.findall(r"[A-Za-z]", ln)) >= 6 and not re.search(r"\b(invoice|proforma|packing|date|page)\b", ln, re.I)
                and not re.search(r"\d{3,}", ln)):
            supplier_name = ln
            nxt = head[idx + 1] if idx + 1 < len(head) else ""
            if nxt and not re.search(r"\b(invoice|proforma|packing)\b", nxt, re.I):
                supplier_address = nxt
            break
    def grab(pattern, group=1):
        m = re.search(pattern, flat, re.I)
        return m.group(group).strip() if m else None

    def weight(label):
        m = re.search(label + r"\s*(?:weight|wt|mass)\.?\s*(?:\(kgs?\))?\s*[:\-]?\s*([\d.,]+)\s*(kgs?|lbs?)?", flat, re.I)
        if not m:
            return None
        n = parse_amount(m.group(1))
        if n is not None and (m.group(2) or "").lower().startswith("lb"):
            n = round(n * 0.45359237, 2)
        return n

    total = None
    for m in re.finditer(r"(?:grand\s*total|total\s*amount|invoice\s*total|amount\s*due|total\s*(?:" + _CURRENCIES +
                         r"|value)?)\s*[:\-]?\s*(?:[A-Z]{3}|\$)?\s*([\d.,]*\d)", flat, re.I):
        total = parse_amount(m.group(1))
    cur = grab(r"\b(" + _CURRENCIES + r")\b")
    header = {
        "supplier_name": supplier_name,
        "supplier_address": supplier_address,
        "invoice_no": grab(r"invoice\s*(?:no|number|#)\.?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})"),
        "invoice_date": grab(r"(?:invoice\s*)?date\s*[:\-]?\s*(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|"
                             r"\d{1,2}[\s\-]+[A-Za-z]{3,9}[\s\-,]+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"),
        "currency": (cur.upper().replace("RMB", "CNY") if cur else ("USD" if "$" in flat else None)),
        "invoice_total": total,
        "incoterm": grab(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b"),
        "bl_awb_no": grab(r"(?:B/L|\bBL|bill of lading|AWB|air ?waybill)\s*(?:no|number|#)?\.?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-]{5,})"),
        "vessel_flight": grab(r"(?:vessel|flight)\s*(?:name|no)?\.?\s*[:\-]\s*([^\n]{3,40}?)(?:\s{2,}|\s+voy|\n|$)"),
        "port_of_loading": grab(r"port of loading\s*[:\-]?\s*([A-Za-z ,]{3,40})"),
        "total_packages": parse_amount(grab(r"(?:total\s*)?(?:no\.?\s*of\s*)?(?:packages|pkgs|cartons|ctns)\s*[:\-]?\s*(\d{1,5})")),
        "gross_weight_kg": weight("gross"),
        "net_weight_kg": weight("net"),
        "freight": parse_amount(grab(r"freight\s*(?:charges?)?\s*[:\-]?\s*(?:[A-Z]{3}|\$)?\s*([\d.,]*\d)")),
        "insurance": parse_amount(grab(r"insurance\s*[:\-]?\s*(?:[A-Z]{3}|\$)?\s*([\d.,]*\d)")),
        "discount": parse_amount(grab(r"discount\s*[:\-]?\s*(?:[A-Z]{3}|\$)?\s*-?([\d.,]*\d)")),
    }
    if re.search(r"\b(B/L|bill of lading|vessel)\b", flat, re.I):
        header["transport_mode"] = "Sea"
    elif re.search(r"\b(AWB|air ?waybill|flight)\b", flat, re.I):
        header["transport_mode"] = "Air"

    notes = ["Read without AI from OCR text. Check every line against the page."]
    if not items:
        notes.append("No item rows were recognised. Try a straighter, sharper scan, add an API key, or type the lines in.")
    return {"header": header, "items": items, "notes": notes}


# ── Mapping onto the generator's fields ──────────────────────

_INCOTERMS = {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}
_MODES = {"sea": "1", "ocean": "1", "air": "2", "courier": "2", "post": "2", "road": "3", "rail": "4"}


def _num(v):
    return parse_amount(v) if isinstance(v, str) else (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)


def _text(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""


def _country(v) -> str:
    s = _text(v).upper()
    return s if re.fullmatch(r"[A-Z]{2,3}", s) else ""


def to_form(raw: dict, engine: str) -> dict:
    """Map a raw scan (Declaration Desk shape) onto the manual-entry form's field names."""
    h = raw.get("header") or {}
    general: dict = {}

    def put(key, value):
        if value not in (None, ""):
            general[key] = value

    exporter = _text(h.get("supplier_name"))
    if exporter and _text(h.get("supplier_address")):
        exporter = f"{exporter}, {_text(h.get('supplier_address'))}"
    put("exporter", exporter)
    put("consignee_name", _text(h.get("consignee_name")))
    put("country_of_export", _country(h.get("country_of_export")) or _country(h.get("supplier_country")))
    put("trading_country", _country(h.get("supplier_country")) or _country(h.get("country_of_export")))
    put("bl_number", _text(h.get("bl_awb_no")))
    put("vessel_name", _text(h.get("vessel_flight")))
    incoterm = _text(h.get("incoterm")).upper().replace("C&F", "CFR")
    put("delivery_terms", incoterm if incoterm in _INCOTERMS else "")
    put("invoice_amount", _num(h.get("invoice_total")))
    currency = _text(h.get("currency")).upper()
    put("invoice_currency", currency if re.fullmatch(r"[A-Z]{3}", currency) else "")
    put("external_freight", _num(h.get("freight")))
    put("insurance", _num(h.get("insurance")))
    put("other_costs", _num(h.get("other_charges")))
    put("deductions", _num(h.get("discount")))
    packages = _num(h.get("total_packages"))
    put("total_packages", int(packages) if packages is not None else None)
    put("mode_transport", _MODES.get(_text(h.get("transport_mode")).lower(), ""))
    for cur_key in ("freight_currency", "insurance_currency", "other_costs_currency"):
        if general.get("invoice_currency"):
            general[cur_key] = general["invoice_currency"]

    items = []
    for it in raw.get("items") or []:
        if not isinstance(it, dict):
            continue
        desc = _text(it.get("description"))
        price = _num(it.get("total_price"))
        if not desc and price is None:
            continue
        qty, unit_price = _num(it.get("quantity")), _num(it.get("unit_price"))
        if price is None and qty is not None and unit_price is not None:
            price = round(qty * unit_price, 2)
        conf = it.get("hs_confidence") if it.get("hs_confidence") in ("high", "medium", "low") else "low"
        packages = _num(it.get("packages"))
        item = {
            "description": desc,
            "hs_suggested": normalize_hs_code(it.get("hs_code")),
            "hs_confidence": conf,
            "country_origin": _country(it.get("origin")),
            "gross_mass": _num(it.get("gross_weight_kg")),
            "net_mass": _num(it.get("net_weight_kg")),
            "item_price": price,
            "supp_units": qty,
            "unit": _text(it.get("unit")).upper(),
            "unit_price": unit_price,
            "no_packages": int(packages) if packages is not None else None,
            "package_kind": _text(it.get("package_type")).upper(),
            "brand": _text(it.get("brand")),
            "model": _text(it.get("model")),
        }
        items.append({k: v for k, v in item.items() if v not in (None, "")})

    extra = {k: h.get(k) for k in ("invoice_no", "invoice_date", "gross_weight_kg", "net_weight_kg",
                                    "port_of_loading", "port_of_discharge") if h.get(k) not in (None, "")}
    notes = [str(n) for n in (raw.get("notes") or []) if n]

    # Every SAD item needs a gross mass (box 35). When the documents only give a
    # shipment total, spread it over the lines by value and say so.
    total_gw = _num(extra.get("gross_weight_kg"))
    value = sum(it.get("item_price") or 0 for it in items)
    if total_gw and value and items and not any(it.get("gross_mass") for it in items):
        for it in items:
            it["gross_mass"] = round(total_gw * (it.get("item_price") or 0) / value, 3)
            it["gross_mass_allocated"] = True
        notes.append(f"Only a shipment gross weight ({total_gw:,.1f} kg) was given, so it was spread over the lines "
                     "by value. Replace with real line weights if you have them.")
    return {"engine": engine, "general": general, "items": items, "invoice": extra, "notes": notes,
            "checks": build_checks(general, items, extra)}


# ── Checks ───────────────────────────────────────────────────

def build_checks(general: dict, items: list[dict], invoice: dict) -> list[dict]:
    """Cross-checks between the lines and the header, as ``{level, text}``."""
    checks: list[dict] = []

    def add(level, text):
        checks.append({"level": level, "text": text})

    if not items:
        add("err", "No item lines were found.")
        return checks
    bad = [i for i, it in enumerate(items, 1)
           if None not in (it.get("supp_units"), it.get("unit_price"), it.get("item_price"))
           and abs(it["supp_units"] * it["unit_price"] - it["item_price"]) > max(0.05, it["item_price"] * 0.002)]
    if bad:
        add("err", f"Qty × unit price doesn't match the line total on line(s) {', '.join(map(str, bad))}.")
    else:
        add("ok", "Every line total equals qty × unit price.")

    lines = sum(it.get("item_price") or 0 for it in items)
    inv = general.get("invoice_amount")
    if inv is not None:
        net = lines - (general.get("deductions") or 0)
        with_charges = net + sum(general.get(k) or 0 for k in ("external_freight", "insurance", "other_costs"))
        if abs(lines - inv) <= 0.05 or abs(net - inv) <= 0.05:
            add("ok", f"Lines add up to the invoice total ({inv:,.2f}).")
        elif abs(with_charges - inv) <= 0.05:
            add("warn", "The invoice total includes freight/insurance — make sure they aren't counted twice.")
        else:
            add("err", f"Lines total {lines:,.2f} but the invoice says {inv:,.2f} (difference {lines - inv:,.2f}).")
    else:
        add("warn", "No invoice total was found, so the line sum can't be checked.")

    gw = _num(invoice.get("gross_weight_kg"))
    line_gw = sum(it.get("gross_mass") or 0 for it in items)
    if gw and line_gw and abs(line_gw - gw) > 0.5:
        add("warn", f"Line gross weights total {line_gw:,.1f} kg; the documents say {gw:,.1f} kg.")
    pk = general.get("total_packages")
    line_pk = sum(it.get("no_packages") or 0 for it in items)
    if pk and line_pk and line_pk != pk:
        add("warn", f"Line packages total {line_pk}; the documents say {pk}.")
    if not general.get("bl_number"):
        add("warn", "No B/L or AWB number was found (box 7) — add it from the transport document.")
    if not any(it.get("country_origin") for it in items):
        add("warn", "No country of origin was found (box 34).")
    return checks


# ── HS codes anchored to the Maldives Customs tariff ─────────

_WORD_RE = re.compile(r"[a-z]{3,}")


def _overlap(a: str, b: str) -> int:
    return len(set(_WORD_RE.findall(a.lower())) & set(_WORD_RE.findall(b.lower())))


async def _resolve_one(item: dict) -> None:
    desc = item.get("description") or ""
    suggested = item.get("hs_suggested") or ""
    candidates: list[dict] = []
    if len(suggested) >= 6:
        # Search the tariff by the suggested heading and keep national codes under it.
        prefix = suggested[:6]
        rows = [r for r in await hs_lookup._search(prefix) if r["hs_code"].startswith(prefix)]
        longer = [r for r in rows if r["hs_code"].startswith(suggested)] if len(suggested) > 6 else []
        candidates = sorted(longer or rows, key=lambda r: -_overlap(desc, r.get("description", "")))
    if not candidates and desc:
        found = await hs_lookup.lookup_hs_candidates(desc, limit=10)
        # stable sort: keep the tariff site's order among equally good matches
        candidates = sorted(found, key=lambda r: -_overlap(desc, r.get("description", "")))
    candidates = candidates[:5]
    item["hs_candidates"] = [{k: c.get(k) for k in ("hs_code", "description", "duty_rate", "safta_rate", "cmfta_rate",
                                                     "hs_unit")} for c in candidates]
    if candidates:
        top = candidates[0]
        item["hs_code"] = top["hs_code"]
        item["duty_rate"] = top.get("duty_rate")
        item["hs_source"] = "tariff" if len(suggested) >= 6 and top["hs_code"].startswith(suggested[:6]) else "search"
    elif suggested:
        item["hs_code"] = suggested
        item["hs_source"] = "suggested"


async def resolve_hs_codes(items: list[dict]) -> list[dict]:
    """Turn each item's suggested HS code (or description) into a national Maldives tariff code."""
    await asyncio.gather(*(_resolve_one(it) for it in items))
    return items
