"""Command-line entry point.

    python -m sad_generator                      # start the web app (default)
    python -m sad_generator serve --port 9000 --host 0.0.0.0
    python -m sad_generator generate shipment.xlsx [-o out.xls] [--no-lookup] [--preferential safta]
    python -m sad_generator template [-o SAD_Input_Template.xls]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__, config


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="  [%(levelname)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import app

    if args.output_dir:
        config.OUTPUT_DIR = Path(args.output_dir).expanduser()
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    shown_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    url = f"http://{shown_host}:{args.port}"
    bar = "=" * 58
    print(f"\n{bar}\n  ASYCUDA SAD Generator v{__version__}\n{bar}")
    print(f"  Open in browser: {url}")
    print(f"  API docs:        {url}/docs")
    print(f"  Output folder:   {config.OUTPUT_DIR.resolve()}")
    if args.host == "0.0.0.0":
        print("  Network access:  ON (other computers on your network can connect)")
    print(f"  Stop:            press Ctrl+C\n{bar}\n")

    if args.open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    from . import service
    from .excel_io import read_input_excel

    src = Path(args.input)
    if not src.is_file():
        print(f"Input file not found: {src}", file=sys.stderr)
        return 2
    data = read_input_excel(src)
    if not data["items"]:
        print("No items found in the workbook.", file=sys.stderr)
        return 1
    out_path = Path(args.output) if args.output else None
    result = asyncio.run(service.generate(
        data,
        preferential=args.preferential,
        lookup=not args.no_lookup,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        output_path=out_path,
    ))
    s = result.duty_summary
    cur = s.get("currency", "")
    print(f"\n  SAD (model):  {result.output_path}")
    print(f"  Duty sheet:   {result.duty_sheet_path}")
    print(f"  Items:        {len(result.items)}  (HS auto-filled: {result.hs_auto_filled})")
    print(f"  Item value:   {s['total_item_value']:,.2f} {cur}")
    print(f"  Duty ({s['preferential']}): {s['total_duty']:,.2f} {cur}"
          f"  — {s['items_missing_duty']} item(s) without a rate")
    a = result.analytics
    cb, t = a["cost_breakdown"], a["totals"]
    print(f"  Effective:    {t['effective_rate']:.2f}%   CIF {cb['cif']:,.2f}   landed {cb['landed']:,.2f} {cur}")
    print(f"  Mass / pkgs:  {t['gross_mass']:,.1f} kg / {t['packages']:,}")
    print("  By HS chapter:")
    for r in a["by_chapter"]:
        print(f"    {r['key']:>5}  {r['label'][:28]:<28} {r['value']:>14,.2f}  {r['share']:>5.1f}%  duty {r['duty']:,.2f}")
    print("  By origin:")
    for r in a["by_origin"]:
        print(f"    {r['label'][:12]:<12} {r['value']:>14,.2f}  {r['share']:>5.1f}%  ({r['items']} items)")
    for w in s.get("warnings", []):
        print(f"  ! {w}")
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    from .sad_builder import create_input_template
    from .sad_model import blank_model_bytes

    if args.simple:
        out = Path(args.output or "SAD_Input_Template.xls")
        out.write_bytes(create_input_template())
    else:
        out = Path(args.output or "SAD_MODEL.xls")
        out.write_bytes(blank_model_bytes())
    print(f"Template written to {out.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sad_generator", description="ASYCUDA++ SAD file generator")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="start the web app (default)")
    s.add_argument("--host", default=config.HOST,
                   help="interface to bind (default 127.0.0.1; use 0.0.0.0 to allow other computers)")
    s.add_argument("--port", type=int, default=config.PORT)
    s.add_argument("--output-dir", help="where generated SAD files are saved")
    s.add_argument("--no-browser", dest="open_browser", action="store_false",
                   help="don't open the browser automatically")
    s.set_defaults(func=cmd_serve)

    g = sub.add_parser("generate", help="convert one Excel file to a SAD without the web UI")
    g.add_argument("input", help="filled template or native SAD workbook (.xls/.xlsx)")
    g.add_argument("-o", "--output", help="output .xls path (default: sad_output/SAD_<BL>_<time>.xls)")
    g.add_argument("--output-dir", help="folder for the output file")
    g.add_argument("--preferential", choices=["general", "safta", "cmfta"], default="general",
                   help="tariff column used for duty (default general)")
    g.add_argument("--no-lookup", action="store_true", help="skip online HS / tariff lookups")
    g.set_defaults(func=cmd_generate)

    t = sub.add_parser("template", help="write a blank input file")
    t.add_argument("-o", "--output", default=None,
                   help="output path (default SAD_MODEL.xls, or SAD_Input_Template.xls with --simple)")
    t.add_argument("--simple", action="store_true",
                   help="the simple two-sheet template instead of the ASYCUDA SAD model")
    t.set_defaults(func=cmd_template)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    if not args.command:  # double-click / no arguments → web app
        args = parser.parse_args(["serve", *(argv or [])])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
