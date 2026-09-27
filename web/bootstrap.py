"""Run the SAD Generator inside the browser (Pyodide) for the online edition.

The FastAPI app is used unchanged. This module only adapts it to the browser:

* there are no threads, so work FastAPI/Starlette/anyio would push to a thread
  pool runs inline;
* outbound requests (Customs tariff, exchange rates, Anthropic) go through the
  browser's ``fetch`` — sites that don't allow cross-origin reads (CORS) are
  retried through the tariff proxy chosen in the page, if any;
* ``asgi_call`` hands a request from the page's ``fetch`` shim to the app.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from urllib.parse import quote, urlencode

sys.path.insert(0, "/home/pyodide/app")
os.environ.setdefault("SAD_OUTPUT_DIR", "/home/pyodide/sad_output")

import anyio.to_thread  # noqa: E402
import starlette.concurrency  # noqa: E402
from pyodide.ffi import to_js  # noqa: E402
from pyodide.http import pyfetch  # noqa: E402

import js  # noqa: E402


# ── No threads in the browser: run "threaded" work inline ────

async def _run_sync(func, *args, abandon_on_cancel=False, cancellable=None, limiter=None):
    return func(*args)


async def _run_in_threadpool(func, *args, **kwargs):
    return func(*args, **kwargs)


anyio.to_thread.run_sync = _run_sync
starlette.concurrency.run_in_threadpool = _run_in_threadpool
for _name in ("starlette.datastructures", "starlette.routing", "starlette.responses", "fastapi.routing",
              "fastapi.dependencies.utils", "fastapi.concurrency"):
    try:
        _mod = importlib.import_module(_name)
    except ImportError:
        continue
    if hasattr(_mod, "run_in_threadpool"):
        _mod.run_in_threadpool = _run_in_threadpool

from sad_generator import config, exchange, hs_lookup, invoice_scan  # noqa: E402
from sad_generator.app import app  # noqa: E402

# ── Network through the browser ──────────────────────────────

SETTINGS = {"proxy": ""}   # set by the page (tariff proxy for sites without CORS)


def set_proxy(url: str) -> None:
    SETTINGS["proxy"] = (url or "").strip()


class FetchError(Exception):
    pass


async def _get_text(url: str, params: dict | None = None) -> str:
    """GET a page directly, or through the proxy when the site blocks cross-origin reads."""
    full = url + ("?" + urlencode(params) if params else "")
    attempts = [full]
    if SETTINGS["proxy"]:
        attempts.append(SETTINGS["proxy"] + quote(full, safe=""))
    last = "no attempt"
    for target in attempts:
        try:
            r = await pyfetch(target)
            if r.ok:
                return await r.string()
            last = f"HTTP {r.status}"
        except Exception as exc:  # noqa: BLE001 — CORS and network failures surface as JS errors
            last = str(exc)[:120]
    raise FetchError(last)


async def _search(term: str) -> list[dict]:
    """Tariff search (same cache semantics as the server version)."""
    import time
    key = term.strip().lower()
    now = time.monotonic()
    hit = hs_lookup._cache.get(key)
    if hit and now - hit[0] < config.HS_CACHE_TTL:
        return hit[1]
    try:
        html = await _get_text(config.HS_SEARCH_URL, {"hsSearchIn": term})
    except FetchError as exc:
        print(f"[tariff] search failed for {term[:40]!r}: {exc}")
        return []
    rows = hs_lookup.parse_tariff_rows(html)
    hs_lookup._cache[key] = (now, rows)
    return rows


async def _fetch_rates(force: bool = False) -> dict:
    import time
    now = time.monotonic()
    cache = exchange._cache
    if not force and cache["rates"] and now - cache["at"] < config.FX_CACHE_TTL:
        return cache["rates"]
    try:
        rates = exchange.parse_exchange_table(await _get_text(config.FX_URL))
    except FetchError as exc:
        print(f"[fx] exchange rates unavailable: {exc}")
        return {}
    if len(rates) > 1:
        cache.update(at=now, rates=rates)
    return rates


hs_lookup._search = _search
exchange.fetch_rates = _fetch_rates


class _Response:
    def __init__(self, status: int, text: str):
        self.status_code, self.text = status, text

    def json(self):
        return json.loads(self.text)


class _BrowserClient:
    """Just enough of ``httpx.AsyncClient`` for the Anthropic call in invoice_scan."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):  # noqa: A002 — mirrors httpx
        headers = dict(headers or {})
        headers["anthropic-dangerous-direct-browser-access"] = "true"
        import json as _json
        try:
            r = await pyfetch(url, method="POST", headers=headers, body=_json.dumps(json))
        except Exception as exc:  # noqa: BLE001
            raise FetchError(str(exc)[:200]) from exc
        return _Response(r.status, await r.string())


class _HttpxShim:
    AsyncClient = _BrowserClient
    HTTPError = FetchError


invoice_scan.httpx = _HttpxShim


# ── ASGI bridge for the page's fetch shim ────────────────────

async def asgi_call(method: str, path: str, query: str, headers_json: str, body):
    data = body.to_bytes() if body is not None else b""
    headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in json.loads(headers_json)]
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
        "method": method.upper(), "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(), "root_path": "", "headers": headers,
        "client": ("browser", 0), "server": ("pyodide", 443),
    }
    done = asyncio.Event()
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": data, "more_body": False}
        await done.wait()
        return {"type": "http.disconnect"}

    status, out_headers, chunks = 500, [], []

    async def send(message):
        nonlocal status, out_headers
        if message["type"] == "http.response.start":
            status = message["status"]
            out_headers = [[k.decode("latin-1"), v.decode("latin-1")] for k, v in message.get("headers", [])]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                done.set()

    try:
        await app(scope, receive, send)
    finally:
        done.set()
    payload = b"".join(chunks)
    return to_js({"status": status, "headers": out_headers, "body": memoryview(payload)},
                 dict_converter=js.Object.fromEntries)
