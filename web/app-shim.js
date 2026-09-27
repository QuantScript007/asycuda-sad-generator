/* Online edition: run the SAD Generator's Python app in the browser with Pyodide.
 *
 * The page is the same index.html the local server shows. This script, loaded
 * first, answers the page's requests to /api/…, /generate, /output/… and
 * /download-… by calling the FastAPI app inside Pyodide instead of a server,
 * and turns download links into in-browser downloads.
 */
(() => {
  'use strict';
  const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.27.2/full/';
  const BASE = new URL('.', document.currentScript.src).href;
  const APP_ROUTES = /^\/(api\/|generate$|output\/|download-model|download-template)/;
  const OUT_DIR = '/home/pyodide/sad_output';
  const realFetch = window.fetch.bind(window);

  // ── Loading overlay ─────────────────────────────────
  const overlay = document.createElement('div');
  overlay.id = 'onlineBoot';
  overlay.innerHTML = `
    <div class="ob-card">
      <div class="ob-logo">SAD</div>
      <div class="ob-title">Starting the SAD Generator</div>
      <div class="ob-text" id="obText">Downloading the app (about 25 MB the first time, then cached)…</div>
      <div class="ob-bar"><i id="obBar"></i></div>
      <div class="ob-note">Everything runs in this browser. Your documents are not uploaded anywhere.</div>
    </div>`;
  const style = document.createElement('style');
  style.textContent = `
    #onlineBoot{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;
      background:rgba(15,23,42,.55);backdrop-filter:blur(3px);padding:16px;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
    #onlineBoot .ob-card{background:#fff;color:#0f172a;border-radius:16px;padding:26px 24px;max-width:420px;width:100%;
      box-shadow:0 20px 50px rgba(0,0,0,.25);text-align:center}
    #onlineBoot .ob-logo{display:inline-flex;width:48px;height:48px;border-radius:12px;align-items:center;justify-content:center;
      color:#fff;font-weight:800;background:linear-gradient(135deg,#F97316,#EC4899);margin-bottom:10px}
    #onlineBoot .ob-title{font-weight:700;font-size:17px}
    #onlineBoot .ob-text{font-size:13px;color:#475569;margin:6px 0 14px;min-height:36px}
    #onlineBoot .ob-bar{height:6px;border-radius:99px;background:#e2e8f0;overflow:hidden}
    #onlineBoot .ob-bar i{display:block;height:100%;width:5%;background:linear-gradient(90deg,#F97316,#EC4899);transition:width .4s}
    #onlineBoot .ob-note{font-size:11px;color:#94a3b8;margin-top:12px}
    #onlineBoot.err .ob-bar i{background:#dc2626}
    .online-note{font-size:12px;color:var(--text-muted)}`;
  document.head.appendChild(style);
  const showOverlay = () => { if (!overlay.isConnected) document.body.appendChild(overlay); };
  if (document.body) showOverlay(); else document.addEventListener('DOMContentLoaded', showOverlay);
  const progress = (pct, text) => {
    const bar = document.getElementById('obBar'); const t = document.getElementById('obText');
    if (bar) bar.style.width = pct + '%';
    if (t && text) t.textContent = text;
  };

  // ── Boot Pyodide + the app ──────────────────────────
  const loadScript = (src) => new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.onload = resolve;
    s.onerror = () => reject(new Error('Could not download ' + src + '. Check your internet connection.'));
    document.head.appendChild(s);
  });

  let pyodide = null;
  const ready = (async () => {
    progress(8, 'Downloading Python for the browser…');
    await loadScript(PYODIDE + 'pyodide.js');
    pyodide = await window.loadPyodide({ indexURL: PYODIDE });
    progress(35, 'Loading libraries…');
    await pyodide.loadPackage(['micropip', 'pydantic', 'beautifulsoup4', 'xlrd', 'httpx']);
    progress(55, 'Installing the app…');
    const wheels = await (await realFetch(BASE + 'py/wheels.json')).json();
    const micropip = pyodide.pyimport('micropip');
    await micropip.install.callKwargs(wheels.map(w => BASE + 'py/wheels/' + w), { deps: false });
    micropip.destroy();
    const zip = await (await realFetch(BASE + 'py/sad_generator.zip')).arrayBuffer();
    pyodide.unpackArchive(zip, 'zip', { extractDir: '/home/pyodide/app' });

    // Keep generated files between visits (IndexedDB), when the browser allows it
    try {
      pyodide.FS.mkdirTree(OUT_DIR);
      pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, OUT_DIR);
      await new Promise(r => pyodide.FS.syncfs(true, () => r()));
    } catch (e) { /* history then lasts for this tab only */ }

    progress(80, 'Starting…');
    const boot = await (await realFetch(BASE + 'py/bootstrap.py')).text();
    await pyodide.runPythonAsync(boot);
    let proxy = '';
    try { proxy = localStorage.getItem('sad-tariff-proxy') || ''; } catch (e) {}
    pyodide.globals.get('set_proxy')(proxy);
    progress(100, 'Ready');
    overlay.remove();
    return pyodide;
  })();
  ready.catch(err => {
    overlay.classList.add('err');
    progress(100, 'The app could not start: ' + (err && err.message ? err.message : err) + ' Reload the page to try again.');
  });

  const persist = () => { try { pyodide.FS.syncfs(false, () => {}); } catch (e) {} };

  // ── Requests to the app ─────────────────────────────
  async function callApp(req) {
    const py = await ready;
    const url = new URL(req.url);
    const body = ['GET', 'HEAD'].includes(req.method) ? null : new Uint8Array(await req.arrayBuffer());
    const headers = JSON.stringify([...req.headers.entries()]);
    const asgi = py.globals.get('asgi_call');
    const res = await asgi(req.method, url.pathname, url.search.replace(/^\?/, ''), headers, body);
    asgi.destroy();
    if (!['GET', 'HEAD'].includes(req.method)) persist();
    return new Response(req.method === 'HEAD' ? null : res.body, { status: res.status, headers: res.headers });
  }

  window.fetch = function (input, init) {
    let req;
    try { req = new Request(input, init); } catch (e) { return realFetch(input, init); }
    const url = new URL(req.url);
    if (url.origin === location.origin && APP_ROUTES.test(url.pathname)) return callApp(req);
    return realFetch(input, init);
  };

  // Download links (/output/…, /download-model…) become in-browser downloads
  document.addEventListener('click', async (e) => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a) return;
    const url = new URL(a.getAttribute('href'), location.href);
    if (url.origin !== location.origin || !APP_ROUTES.test(url.pathname)) return;
    e.preventDefault();
    try {
      const r = await callApp(new Request(url.href));
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'HTTP ' + r.status);
      const blob = await r.blob();
      const cd = r.headers.get('content-disposition') || '';
      const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
      const name = decodeURIComponent(m ? m[1] : url.pathname.split('/').pop() || 'download');
      if (url.pathname.startsWith('/api/')) { window.open(URL.createObjectURL(blob), '_blank'); return; }
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob); link.download = name;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    } catch (err) {
      alert('Download failed: ' + (err.message || err));
    }
  }, true);

  // ── Online-edition touches to the page ──────────────
  document.addEventListener('DOMContentLoaded', () => {
    const sub = document.querySelector('.brand-sub');
    if (sub) sub.textContent = sub.textContent.replace('Local Edition', 'Online Edition');
    const pill = document.querySelector('.top-actions .pill');
    if (pill) pill.textContent = 'Runs in your browser';
    // No API docs server online
    document.querySelectorAll('a[href="/docs"], button[onclick*="/docs"], a[href="/api/history"]').forEach(el => el.remove());
    const out = document.getElementById('outputDir');
    if (out) out.textContent = 'this browser (saved until you clear site data)';

    // Tariff proxy setting, next to the scan reading settings
    const settings = document.getElementById('scanSettings');
    if (settings) {
      const box = document.createElement('div');
      box.style.marginTop = '12px';
      let value = '';
      try { value = localStorage.getItem('sad-tariff-proxy') || ''; } catch (e) {}
      box.innerHTML = `
        <label class="form-field"><span class="form-label">Tariff proxy (online edition)</span>
          <input type="url" class="form-input" id="tariffProxy" placeholder="e.g. https://your-proxy.example/?url=" value="${value.replace(/"/g, '&quot;')}"></label>
        <div class="online-note">Browsers may block this page from reading customs.gov.mv directly. If HS codes, duty rates or exchange rates stay empty online, enter a CORS proxy here (the address is added in front of the Customs URL), type HS codes yourself, or use the desktop app, which has no such limit.</div>`;
      settings.appendChild(box);
      box.querySelector('input').addEventListener('change', async (ev) => {
        const v = ev.target.value.trim();
        try { v ? localStorage.setItem('sad-tariff-proxy', v) : localStorage.removeItem('sad-tariff-proxy'); } catch (e) {}
        (await ready).globals.get('set_proxy')(v);
      });
    }
  });
})();
