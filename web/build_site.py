"""Build the online (GitHub Pages) edition into a static folder.

    python web/build_site.py [--out _site] [--wheels-from DIR]

Output:
    index.html            the app's own page, with the online shim loaded first
    app-shim.js           runs the app in the browser (Pyodide)
    py/bootstrap.py       browser adaptations + ASGI bridge
    py/sad_generator.zip  the Python package (code + SAD model template)
    py/wheels/*.whl       pure-Python dependencies pinned in web/requirements-web.txt
    py/wheels.json        list of those wheels
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PKG = ROOT / "sad_generator"


def version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (PKG / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "0"


def build(out: Path, wheels_from: Path | None = None) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "py" / "wheels").mkdir(parents=True)

    html = (PKG / "static" / "index.html").read_text(encoding="utf-8").replace("{{VERSION}}", version())
    html = html.replace("<head>", '<head>\n<script src="app-shim.js"></script>', 1)
    html = html.replace("<title>", '<meta name="description" content="Scan invoices and generate ASYCUDA SAD files for Maldives Customs, in your browser.">\n<title>', 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    shutil.copy(WEB / "app-shim.js", out / "app-shim.js")
    shutil.copy(WEB / "bootstrap.py", out / "py" / "bootstrap.py")
    (out / ".nojekyll").write_text("")

    with zipfile.ZipFile(out / "py" / "sad_generator.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(PKG.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc" and "static" not in f.parts:
                zf.write(f, f.relative_to(ROOT).as_posix())

    wheel_dir = out / "py" / "wheels"
    reqs = [ln.strip() for ln in (WEB / "requirements-web.txt").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    if wheels_from:
        for w in Path(wheels_from).glob("*.whl"):
            shutil.copy(w, wheel_dir / w.name)
    else:
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
                        "--python-version", "3.12", "--implementation", "py", "--abi", "none",
                        "--platform", "any", "-d", str(wheel_dir), *[r for r in reqs if not r.startswith("xlwt")]],
                       check=True)
        # xlwt only publishes a py2.py3 wheel
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "-d", str(wheel_dir),
                        *[r for r in reqs if r.startswith("xlwt")]], check=True)
    wheels = sorted(p.name for p in wheel_dir.glob("*.whl"))
    wanted = {re.split(r"==", r)[0].replace("-", "_").lower() for r in reqs}
    have = {w.split("-")[0].lower() for w in wheels}
    missing = wanted - have
    if missing:
        raise SystemExit(f"Missing wheels: {', '.join(sorted(missing))}")
    (out / "py" / "wheels.json").write_text(json.dumps(wheels, indent=1))
    print(f"Built {out} (v{version()}, {len(wheels)} wheels)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "_site"))
    ap.add_argument("--wheels-from", help="use wheels from this folder instead of downloading them")
    a = ap.parse_args()
    build(Path(a.out), Path(a.wheels_from) if a.wheels_from else None)
