#!/usr/bin/env python3
"""ASYCUDA SAD Generator — launcher.

Kept at the project root so the existing .bat launchers, desktop shortcuts and
PyInstaller build keep working. All the code now lives in the ``sad_generator``
package; run ``python sad_generator_local.py --help`` for the options.

    python sad_generator_local.py                       # web app on http://localhost:8000
    python sad_generator_local.py generate input.xlsx   # command-line conversion
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sad_generator.app import app  # noqa: E402,F401  (re-exported for `uvicorn sad_generator_local:app`)
from sad_generator.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
