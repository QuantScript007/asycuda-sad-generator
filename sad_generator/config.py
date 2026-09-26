"""Runtime configuration, overridable through environment variables."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    """Folder that relative paths are resolved against.

    For the PyInstaller .exe this is the folder containing the .exe (so output
    lands next to it, not in a temp unpack folder). Otherwise it is the current
    working directory, matching the original behaviour.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


BASE_DIR = _base_dir()
OUTPUT_DIR = Path(os.environ.get("SAD_OUTPUT_DIR", BASE_DIR / "sad_output")).expanduser()

HOST = os.environ.get("SAD_HOST", "127.0.0.1")
PORT = _env_int("SAD_PORT", 8000)

# Maldives Customs tariff search
HS_SEARCH_URL = os.environ.get("SAD_HS_SEARCH_URL", "https://www.customs.gov.mv/eServices/findtariff")
HS_TIMEOUT = _env_float("SAD_HS_TIMEOUT", 15.0)
HS_MAX_CONCURRENCY = _env_int("SAD_HS_MAX_CONCURRENCY", 4)
HS_CACHE_TTL = _env_int("SAD_HS_CACHE_TTL", 6 * 60 * 60)  # seconds
HS_RETRIES = _env_int("SAD_HS_RETRIES", 1)

# Maldives Customs exchange rates (MVR per unit of foreign currency)
FX_URL = os.environ.get("SAD_FX_URL", "https://customs.gov.mv/eServices/exchangeRate")
FX_CACHE_TTL = _env_int("SAD_FX_CACHE_TTL", 6 * 60 * 60)

# Revenue charged per item = item price × MVR rate × REVENUE_RATE (1%)
REVENUE_RATE = _env_float("SAD_REVENUE_RATE", 0.01)

# Uploads
MAX_UPLOAD_MB = _env_int("SAD_MAX_UPLOAD_MB", 20)
HISTORY_LIMIT = _env_int("SAD_HISTORY_LIMIT", 50)

# Scan invoice (Claude). The key can also be typed into the Scan settings in the browser.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
SCAN_MODEL = os.environ.get("SAD_SCAN_MODEL", "claude-sonnet-5")
SCAN_TIMEOUT = _env_float("SAD_SCAN_TIMEOUT", 180.0)
SCAN_MAX_FILES = _env_int("SAD_SCAN_MAX_FILES", 20)
