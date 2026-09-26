"""Small parsing / normalisation helpers shared across modules."""

from __future__ import annotations

import re

_FLOAT_INT_RE = re.compile(r"^\d+\.0+$")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def normalize_hs_code(value) -> str:
    """Return an HS / commodity code as a clean string of digits.

    Handles the common ways a code gets mangled on its way through Excel:

    * stored as a number, so ``0603120011`` arrives as ``603120011`` or
      ``603120011.0`` — the lost leading zero is restored (HS codes always
      have an even number of digits: 6, 8, 10 or 12);
    * written with separators, e.g. ``0603.12.00.11`` or ``0603 12 0011``.

    Returns ``""`` for blanks and for the placeholder ``0``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if value != value or value <= 0:  # NaN / zero / negative
            return ""
        s = str(int(value)) if value == int(value) else str(value)
    else:
        s = str(value).strip()
    if _FLOAT_INT_RE.match(s):
        s = s.split(".", 1)[0]
    s = re.sub(r"[\s.\-/]", "", s)
    if not s.isdigit() or set(s) == {"0"}:
        return s if s and not s.isdigit() else ""
    if len(s) in (5, 7, 9, 11):
        s = "0" + s
    return s


def is_valid_hs(code: str) -> bool:
    return bool(code) and code.isdigit() and len(code) >= 8


def parse_number(value, default=None):
    """Parse ints/floats/strings like ``'1,250.50'`` into float; ``default`` otherwise."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return default


def parse_rate(value) -> float | None:
    """Parse a duty-rate value: ``15``, ``'15.5'``, ``'15%'``, ``' 0.00 % '``.

    Anything without a number (``''``, ``'—'``, ``'⏳'``, ``'??'``, ``'Free'``)
    returns ``None`` so callers know the rate is still unknown.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    m = _NUMBER_RE.search(s.replace(",", ""))
    if not m:
        return None
    return float(m.group(0))


def safe_filename_part(value, fallback: str = "unknown", max_len: int = 60) -> str:
    """Make a string safe to embed in a Windows/macOS/Linux filename."""
    s = _UNSAFE_FILENAME_RE.sub("-", str(value or "").strip()).strip("-.")
    return (s[:max_len] or fallback)
