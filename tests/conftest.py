import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sad_generator import config, hs_lookup  # noqa: E402

FAKE_TARIFF = {
    "0603120011": {"hs_code": "0603120011", "description": "Carnations", "hs_unit": "KG",
                   "duty_rate": 25.0, "safta_rate": 10.0, "cmfta_rate": None},
    "1006300099": {"hs_code": "1006300099", "description": "Rice", "hs_unit": "KG",
                   "duty_rate": 0.0, "safta_rate": 0.0, "cmfta_rate": 0.0},
    "6403990099": {"hs_code": "6403990099", "description": "Footwear", "hs_unit": "PR",
                   "duty_rate": 20.0, "safta_rate": 15.0, "cmfta_rate": 5.0},
}


@pytest.fixture(autouse=True)
def offline_lookup(monkeypatch, tmp_path):
    """Never hit the real customs website in tests; isolate the output folder."""
    calls: list[str] = []

    async def fake_search(term: str):
        calls.append(term)
        t = term.strip().lower()
        if t in FAKE_TARIFF:
            return [FAKE_TARIFF[t]]
        if "rice" in t:
            return [FAKE_TARIFF["1006300099"]]
        if "sandal" in t or "shoe" in t:
            return [FAKE_TARIFF["6403990099"]]
        return []

    monkeypatch.setattr(hs_lookup, "_search", fake_search)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "sad_output")
    hs_lookup.clear_cache()
    return calls
