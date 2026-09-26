"""FastAPI web application: the browser UI plus a small JSON API."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from . import __version__, config, exchange, invoice_scan, service
from .analytics import build_analytics
from .duty import PREFERENTIAL_KEYS
from .excel_io import read_input_excel
from .hs_lookup import lookup_hs_candidates, lookup_hs_tariff
from .sad_builder import create_input_template
from .sad_model import blank_model_bytes, model_path
from .utils import normalize_hs_code

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_SUFFIXES = (".xls", ".xlsx", ".xlsm")
XLS_MEDIA_TYPE = "application/vnd.ms-excel"

app = FastAPI(
    title="ASYCUDA++ SAD Generator",
    description="Upload an .xls/.xlsx (or fill in the form) and get a ready-to-import ASYCUDA++ SAD file.",
    version=__version__,
)


# ── Models ───────────────────────────────────────────────────

class GenerateResponse(BaseModel):
    bl_number: str
    vessel: str
    consignee: str
    country_of_export: str
    delivery_terms: str
    item_count: int
    hs_auto_filled: int
    download_url: str
    duty_sheet_url: str = ""
    output_file: str
    items_preview: list[dict] = Field(default_factory=list)
    duty_summary: dict = Field(default_factory=dict)
    analytics: dict = Field(default_factory=dict)


class ManualEntryRequest(BaseModel):
    general: dict = Field(default_factory=dict)
    items: list[dict] = Field(default_factory=list)
    preferential: str = "general"
    exchange_rate: float | None = None


class ScanTextRequest(BaseModel):
    text: str = Field(..., max_length=400_000)
    lookup: bool = True


# ── Helpers ──────────────────────────────────────────────────

def _check_preferential(value: str) -> str:
    v = (value or "general").lower()
    if v not in PREFERENTIAL_KEYS:
        raise HTTPException(422, f"preferential must be one of: {', '.join(PREFERENTIAL_KEYS)}")
    return v


async def _parse_upload(file: UploadFile) -> dict:
    """Save an upload to a temp file, parse it, and always clean up."""
    name = (file.filename or "").lower()
    suffix = next((s for s in ALLOWED_SUFFIXES if name.endswith(s)), None)
    if suffix is None:
        raise HTTPException(415, "Please upload an Excel file (.xls or .xlsx).")
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {config.MAX_UPLOAD_MB} MB.")
    if not content:
        raise HTTPException(422, "The uploaded file is empty.")
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        return read_input_excel(tmp_path)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — report any parse failure to the user
        log.exception("Could not parse %s", file.filename)
        raise HTTPException(422, f"Could not parse file: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Routes ───────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("{{VERSION}}", __version__)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": __version__, "output_dir": str(config.OUTPUT_DIR.resolve())}


@app.get("/api/hs-lookup")
async def api_hs_lookup(description: str = Query("", max_length=200)):
    """Live HS code search against the Maldives Customs tariff (with duty rates)."""
    if not description.strip():
        return {"query": description, "results": []}
    return {"query": description, "results": await lookup_hs_candidates(description.strip())}


@app.get("/api/hs-tariff/{hs_code}")
async def api_hs_tariff(hs_code: str):
    """Duty rate, SAFTA, CMFTA and unit for one HS code."""
    result = await lookup_hs_tariff(hs_code)
    if not result:
        raise HTTPException(404, f"No tariff found for HS code {hs_code}")
    return result


@app.get("/api/exchange-rates")
async def api_exchange_rates(currency: str = Query("USD", max_length=3)):
    """MVR exchange rates from Maldives Customs, and the rate that would be used for ``currency``."""
    rates = await exchange.fetch_rates()
    return {"source_url": config.FX_URL, "rates": rates, "selected": await exchange.resolve_rate(currency),
            "revenue_rate": config.REVENUE_RATE}


@app.post("/api/preview")
async def api_preview(file: UploadFile = File(...)):
    """Parse an uploaded Excel file and return what was found (no SAD is generated)."""
    data = await _parse_upload(file)
    items = data["items"]
    missing = sum(1 for it in items if not normalize_hs_code(it.get("hs_code")))
    return {
        "filename": file.filename,
        "general": data["general"],
        "items": items,
        "stats": {
            "total_items": len(items),
            "missing_hs_codes": missing,
            "will_auto_lookup": missing,
            "has_general_data": bool(data["general"]),
        },
        "warnings": service.validate(data),
        "analytics": build_analytics(data["general"], items),
    }


@app.post("/generate", response_model=GenerateResponse)
async def generate_sad(
    file: UploadFile = File(...),
    preferential: str = Query("general", description="general | safta | cmfta"),
    exchange_rate: float | None = Query(None, gt=0, description="MVR per unit of the invoice currency (default: Customs rate)"),
):
    """Upload a filled Excel file and receive an ASYCUDA++ SAD file."""
    preferential = _check_preferential(preferential)
    data = await _parse_upload(file)
    if not data["items"]:
        raise HTTPException(
            422,
            "No items found. Check your file has an 'Items' sheet with headers in row 1 "
            "(template format) or the native ASYCUDA SAD layout.",
        )
    log.info("Processing upload %s (%d items)", file.filename, len(data["items"]))
    result = await service.generate(data, preferential=preferential, exchange_rate=exchange_rate)
    return GenerateResponse(**result.to_response())


@app.post("/api/generate-manual", response_model=GenerateResponse)
async def generate_sad_manual(payload: ManualEntryRequest):
    """Generate a SAD directly from JSON form data."""
    preferential = _check_preferential(payload.preferential)
    if not payload.items:
        raise HTTPException(422, "Add at least one item before generating.")
    result = await service.generate(
        {"general": payload.general, "items": payload.items}, preferential=preferential,
        exchange_rate=payload.exchange_rate,
    )
    return GenerateResponse(**result.to_response())


# ── Scan invoice ─────────────────────────────────────────────

@app.get("/api/scan/status")
async def scan_status():
    """Whether a server-side Anthropic API key is configured (the browser may also send its own)."""
    return {"server_key": bool(config.ANTHROPIC_API_KEY), "model": config.SCAN_MODEL}


@app.post("/api/scan")
async def scan_documents(
    files: list[UploadFile] = File(...),
    model: str = Form(""),
    lookup: bool = Form(True),
    x_anthropic_key: str | None = Header(None),
):
    """Read scanned invoices / packing lists / B/Ls with Claude and return SAD form data."""
    api_key = (x_anthropic_key or "").strip() or config.ANTHROPIC_API_KEY
    if not api_key:
        raise HTTPException(400, "No Anthropic API key is set. Add one in the Scan settings, or use free reading.")
    if len(files) > config.SCAN_MAX_FILES:
        raise HTTPException(413, f"Scan at most {config.SCAN_MAX_FILES} files at a time.")
    payload, total = [], 0
    for f in files:
        data = await f.read()
        total += len(data)
        media = (f.content_type or "").lower()
        name = f.filename or "document"
        if media not in invoice_scan.IMAGE_TYPES and media != invoice_scan.PDF_TYPE:
            media = invoice_scan.PDF_TYPE if name.lower().endswith(".pdf") else media
        payload.append((name, data, media))
    if total > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"The documents add up to more than {config.MAX_UPLOAD_MB} MB. Scan fewer pages at once.")
    try:
        raw = await invoice_scan.read_with_claude(payload, api_key, model.strip() or None)
    except invoice_scan.ScanError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    result = invoice_scan.to_form(raw, engine="claude")
    if lookup:
        await invoice_scan.resolve_hs_codes(result["items"])
    return result


@app.post("/api/scan-text")
async def scan_text(payload: ScanTextRequest):
    """Parse OCR / PDF text (read free in the browser) into SAD form data."""
    result = invoice_scan.to_form(invoice_scan.parse_invoice_text(payload.text), engine="text")
    if payload.lookup:
        await invoice_scan.resolve_hs_codes(result["items"])
    return result


@app.get("/api/history")
async def api_history():
    """Previously generated SAD files, most recent first."""
    out = config.OUTPUT_DIR
    if not out.exists():
        return {"files": []}
    paths = [p for p in out.iterdir() if p.is_file() and p.suffix.lower() in (".xls", ".xlsx")]
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    files = []
    for p in paths[: config.HISTORY_LIMIT]:
        st = p.stat()
        files.append({
            "name": p.name,
            "url": f"/output/{p.name}",
            "size_kb": round(st.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return {"files": files}


@app.get("/download-template")
async def download_template():
    return Response(
        content=create_input_template(),
        media_type=XLS_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="SAD_Input_Template.xls"'},
    )


@app.get("/download-model")
async def download_model(sample: bool = False):
    """The ASYCUDA SAD model workbook — blank, or with its sample rows (``?sample=true``)."""
    content = model_path().read_bytes() if sample else blank_model_bytes()
    return Response(
        content=content,
        media_type=XLS_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="SAD_MODEL.xls"'},
    )


def _resolve_output(filename: str) -> Path:
    out_dir = config.OUTPUT_DIR.resolve()
    path = (out_dir / filename).resolve()
    if path.parent != out_dir or not path.is_file():
        raise HTTPException(404, "File not found")
    return path


@app.get("/output/{filename}")
async def download_output(filename: str):
    path = _resolve_output(filename)
    return FileResponse(str(path), filename=path.name, media_type=XLS_MEDIA_TYPE)


@app.delete("/output/{filename}")
async def delete_output(filename: str):
    """Remove a generated file from the history."""
    _resolve_output(filename).unlink()
    return {"deleted": filename}
