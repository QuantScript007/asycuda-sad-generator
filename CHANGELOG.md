# Changelog

## 3.5.0 — 2026-10-14

### Added
- **Stronger pre-flight checks** (`sad_generator/validation.py`), shown as warnings with the SAD box number before you import into ASYCUDA:
  - header: country of export and origin must be 2-letter ISO codes, invoice currency a 3-letter code, delivery terms a recognised Incoterm;
  - items add up to the invoice total, and package counts add up to the declared total (1% tolerance for rounding);
  - per item: missing, 6-digit or odd-length HS code, zero / negative / non-numeric price, gross mass or supplementary quantity, fractional or negative package counts;
  - repeated lines flagged as likely duplicates.
- `check_shipment()` returns structured issues (severity, item number, field) for use by other tools; `service.validate()` still returns plain strings.

## 3.4.0 — 2026-09-26

### Added
- **📷 Scan Invoice** — the new default input method (merged in from *Declaration Desk*). Drop scanned or photographed commercial invoices, packing lists and B/Ls (PDF, JPG, PNG, WebP); the header and every line are read into the manual-entry SAD form for review.
  - **With an Anthropic API key** (typed into *Reading settings*, kept only in the browser, or `ANTHROPIC_API_KEY` on the server), Claude reads the pages, merges packing-list weights and package counts onto the invoice lines, and suggests an HS heading for each line.
  - **Without a key**, pages are read free with OCR in the browser (Tesseract.js); digital PDFs use their own text layer.
- **HS codes anchored to the Maldives tariff**: each suggested heading (or, failing that, the description) is searched in the Customs tariff and the best national code under it is picked, with its duty rate. Other matches are offered in the HS field's drop-down.
- **Checks** after reading: qty × unit price vs line total, lines vs invoice total (discount and charges understood), line weights and packages vs the document totals, missing B/L number or origin.
- When only a shipment gross weight is given, it is spread over the lines by value (box 35 is required per item) and highlighted.
- A **Scanned pages** drawer to check the form against the documents while reviewing, with 200% zoom.
- **Supp. Qty (box 41)** column in the manual-entry items table.
- `/api/scan`, `/api/scan-text` and `/api/scan/status` endpoints; `ANTHROPIC_API_KEY`, `SAD_SCAN_MODEL`, `SAD_SCAN_TIMEOUT`, `SAD_SCAN_MAX_FILES` settings.

## 3.3.0 — 2026-09-26

### Added
- **Duty and revenue in MVR**, using the Maldives Customs exchange rate ([customs.gov.mv/eServices/exchangeRate](https://customs.gov.mv/eServices/exchangeRate)):
  - Duty (MVR) = item price × duty % × MVR rate
  - Revenue (MVR) = item price × MVR rate × 0.01
  - Payable (MVR) = duty + revenue
- The rate is fetched from Customs (cached 6 h); a rate typed in the **MVR rate** box, the form's exchange-rate field, `?exchange_rate=` or `--rate` takes priority. If Customs can't be reached, USD falls back to 15.42 with a warning.
- Dashboard tiles for duty, revenue and total payable in MVR; *Duty MVR* and *Revenue MVR* columns in the items table.
- Duty worksheet: *Exchange rate, Value, Duty, Revenue, Payable (MVR)* columns with totals, plus an MVR summary on the General Segment sheet.
- `/api/exchange-rates` endpoint; `SAD_FX_URL`, `SAD_FX_CACHE_TTL`, `SAD_REVENUE_RATE` settings.

## 3.2.0 — 2026-09-26

### Changed
- **The downloaded SAD is now the official ASYCUDA SAD model** (`sad_generator/templates/SAD_MODEL.xls`), filled in with the shipment data. Everything in the model is kept exactly: `General Segment` and `Items` layout, cell styles and text formats, column widths, hidden currency columns (H–Q), merged headers, the customs-office dropdown and all other data-validation rules, and the field-hint comments.
- The previous layout with duty columns is still produced alongside it as a **Duty worksheet** (`…_duty.xls`), downloadable from the result.

### Added
- **Download the SAD model** from Step 1 — blank, or with its sample rows — to fill by hand and upload.
- ASYCUDA field limits from the model are enforced with a warning: description 49 characters, brand / model / size 24, packing codes 5.
- Item-level freight / insurance / other costs / deductions (hidden columns) are written with their currency when present.
- `template` on the command line writes the blank SAD model (`--simple` for the old two-sheet template).
- `SAD_MODEL_PATH` to use an updated model file.
- A small BIFF8 editor (`xls_template.py`) that fills cells without rebuilding the workbook — `xlutils` would have dropped the dropdowns and comments.

## 3.1.0 — 2026-09-26

### Added
- **Shipment dashboard** on every generated SAD and in the file preview (*Insights* tab):
  - KPI tiles — line items, goods value (and value per kg), customs duty with effective rate, CIF value, landed cost, gross mass and packages;
  - cost build-up bar — goods, freight, insurance, other costs, duty;
  - duty (or value) by HS chapter as a donut chart, with chapter names;
  - value by country of origin with flags;
  - items by duty-rate band (0%, 0–10%, 10–20%, 20–30%, >30%, unknown);
  - top 5 dutiable items;
  - checks — items vs declared invoice total, items vs declared package count, HS code source (provided / auto-filled / missing), highest-rate item.
- Line-items table now shows origin, gross mass, packages, brand and SAFTA/CMFTA rates, with colour-coded rate pills; shows up to 500 items (was 50) in a scrollable table.
- New colour theme: gradient hero with live counters, colour-coded steps and cards, gradient stat tiles, coloured history with daily totals. Works in light and dark mode.
- `generate` on the command line prints effective rate, CIF / landed cost, mass, and breakdowns by HS chapter and origin.
- `analytics` object in the `/generate`, `/api/generate-manual` and `/api/preview` responses.

## 3.0.0 — 2026-09-26

### Fixed
- **Manual-entry duty was always 0 in the SAD file.** The form sends rates as `"20%"`, which the server couldn't parse. Rates are now parsed properly, and placeholders like `⏳` / `??` trigger a fresh lookup.
- **HS codes damaged by Excel** — leading zeros lost when a code was stored as a number (`0603120011` → `603120011`) are restored, and `.replace(".0", "")` no longer corrupts dotted codes such as `0603.0120`.
- **Re-uploading a generated SAD** read columns from the wrong positions (v2.2 inserted duty columns) and counted the `TOTAL` row as an extra item. Both layouts are now detected.
- Duty totals only covered the first 50 items; they now cover every item.
- Result currency was hard-coded to `$`/USD; it now uses the invoice currency.
- Output filenames are sanitised for Windows (`/ \ : * ? " < > |` in BL numbers).
- `/output/{file}` is protected against path traversal; uploads are type- and size-checked.
- Error messages shown in the UI are HTML-escaped.
- The `.bat` launcher opened the browser twice and depended on the current folder.

### Added
- **SAFTA / CMFTA preferential tariff** selector (UI, API `preferential=`, CLI `--preferential`), falling back to the general rate when no preferential rate is published.
- **Command line**: `generate`, `template`, `serve` (with `--host`, `--port`, `--output-dir`, `--no-browser`, `--no-lookup`).
- HS search results show Duty / SAFTA / CMFTA rates.
- Input warnings (missing BL, description or price) shown with the result.
- Tariff lookups are cached, rate-limited (4 parallel) and retried once.
- Header aliases for template columns (`HS Code`, `Commodity code`, `Country of origin`, …).
- Styled headers and column widths in the SAD workbook (cell positions unchanged).
- `/api/health`, `DELETE /output/{file}`.
- pytest suite (offline), ruff, GitHub Actions CI and a Windows `.exe` build workflow.

### Changed
- Code split from one 3,000-line file into the `sad_generator` package; `sad_generator_local.py` remains as the launcher, so existing shortcuts keep working.
- The server listens on `127.0.0.1` by default. Pass `--host 0.0.0.0` (or `SAD_HOST=0.0.0.0`) to allow other computers on the network, as before.
- The `.exe` saves output next to itself instead of the current folder.

## 2.2.0
- Duty-rate lookup and calculation, manual entry form, history.
