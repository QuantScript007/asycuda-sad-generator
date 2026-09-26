# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build spec — run:  pyinstaller --clean --noconfirm ASYCUDA_SAD_Generator.spec
# (build_exe.bat and the GitHub "Build Windows .exe" workflow both use this file)
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("sad_generator/static", "sad_generator/static"), ("sad_generator/templates", "sad_generator/templates")]
binaries = []
hiddenimports = collect_submodules("uvicorn") + collect_submodules("sad_generator")

for pkg in ("bs4", "openpyxl", "xlrd", "xlwt", "olefile", "multipart", "python_multipart"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["sad_generator_local.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ASYCUDA_SAD_Generator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
