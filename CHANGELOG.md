# Changelog

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
