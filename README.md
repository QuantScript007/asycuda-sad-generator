# ASYCUDA SAD Generator

Turn a scanned supplier invoice, an Excel sheet or a web form into a ready-to-import **ASYCUDA++ SAD** for **Maldives Customs** — with HS codes, duty and MVR totals looked up automatically. Runs on your own computer.

## Features

- **📷 Scan invoice** – drop invoices, packing lists or B/Ls (PDF or photos). The header and every line are read into the SAD form for review.
  - Free OCR in the browser by default.
  - Add an Anthropic API key for Claude reading: better accuracy, and packing lists merged onto the lines.
- **📁 Excel upload** – the official SAD model, the simple template, or a previously generated SAD.
- **✍️ Manual entry** – fill the SAD form in the browser.
- **HS codes and duty** – matched against the Maldives Customs tariff, with General, SAFTA or CMFTA rates.
- **Duty and revenue in MVR** – uses the Customs exchange rate.
- **Checks** – line totals, invoice total, weights and packages.
- **Output** – the official SAD model filled in, plus a duty worksheet and a shipment dashboard.

## Run it

**Online, full version (GitHub Codespaces):** [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/QuantScript007/asycuda-sad-generator?quickstart=1)
Sign in to GitHub. After about a minute the app opens in a new tab, with live tariff and exchange-rate lookups. GitHub gives 60 free hours a month; stop the codespace when you're done.

**Online, phone version (GitHub Pages):** <https://quantscript007.github.io/asycuda-sad-mobile/> — scan, form and Excel in the browser. Duty % and the MVR rate are typed in there.

**Windows:** double-click `start_sad_generator.bat`. It opens at <http://localhost:8000>. You can also use the `.exe` from Releases.

**macOS / Linux:**
```bash
pip install -r requirements.txt
python sad_generator_local.py
```

Command line: `python sad_generator_local.py generate shipment.xlsx` (see `--help`).

## Settings (optional)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Use Claude for scanning (or type a key in the browser) |
| `SAD_PORT` / `SAD_HOST` | Server address (default `127.0.0.1:8000`) |
| `SAD_OUTPUT_DIR` | Where SAD files are saved (default `./sad_output`) |

The other settings are in `sad_generator/config.py`. The API docs are at `/docs`.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q && ruff check .
```

> HS codes, duty and scanned values are suggestions. Always check them before lodging a declaration. See [CHANGELOG.md](CHANGELOG.md) for version history.
