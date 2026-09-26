# Changelog

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
