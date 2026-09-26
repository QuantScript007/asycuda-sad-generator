@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Build Standalone .exe - ASYCUDA SAD Generator

REM ─────────────────────────────────────────────────────────────
REM  Packages sad_generator_local.py into a single .exe file
REM  using PyInstaller. No Python installation required on
REM  target machines — just copy the .exe and run.
REM ─────────────────────────────────────────────────────────────

for /f %%a in ('echo prompt $E^| cmd') do set "ESC=%%a"
set "RESET=%ESC%[0m"
set "BOLD=%ESC%[1m"
set "DIM=%ESC%[2m"
set "GREEN=%ESC%[32m"
set "YELLOW=%ESC%[33m"
set "RED=%ESC%[31m"
set "CYAN=%ESC%[36m"
set "ORANGE=%ESC%[38;5;208m"

echo.
echo %BOLD%%ORANGE%   ███████ ███████ ██      ██████  ██████   ██████ %RESET%
echo %BOLD%%ORANGE%   ██      ██      ██      ██   ██ ██   ██ ██     %RESET%
echo %BOLD%%ORANGE%   ███████ █████   ██      ██   ██ ██████  ██     %RESET%
echo %BOLD%%ORANGE%        ██ ██      ██      ██   ██ ██   ██ ██     %RESET%
echo %BOLD%%ORANGE%   ███████ ███████ ███████ ██████  ██   ██  ██████%RESET%
echo.
echo %BOLD%            Build Standalone .exe%RESET%
echo.
echo %DIM%   This will package the SAD Generator into a single .exe file.%RESET%
echo %DIM%   Target users won't need Python installed — just the .exe.%RESET%
echo.
echo %DIM%──────────────────────────────────────────────────────────────%RESET%
echo.

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%sad_generator_local.py"
set "VENV_DIR=%SCRIPT_DIR%.venv_build"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "DIST_DIR=%SCRIPT_DIR%dist"
set "BUILD_DIR=%SCRIPT_DIR%build"
set "SPEC_FILE=%SCRIPT_DIR%ASYCUDA_SAD_Generator.spec"
set "EXE_PATH=%DIST_DIR%\ASYCUDA_SAD_Generator.exe"

REM ── Step 1: Locate Python ────────────────────────────────────
echo %BOLD%[1/6]%RESET% %CYAN%Locating Python...%RESET%

where python >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=python"
    goto :py_found
)
where py >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=py -3"
    goto :py_found
)

echo %RED%   ERROR: Python not found. Install Python 3.10+ first.%RESET%
pause
exit /b 1

:py_found
echo   %GREEN%✓%RESET% Using: %DIM%!PY_CMD!%RESET%

REM ── Step 2: Verify script ────────────────────────────────────
echo.
echo %BOLD%[2/6]%RESET% %CYAN%Verifying script...%RESET%
if not exist "%SCRIPT_PATH%" (
    echo %RED%   ERROR: sad_generator_local.py not found in:%RESET%
    echo %BOLD%     %SCRIPT_DIR%%RESET%
    pause
    exit /b 1
)
if not exist "%SCRIPT_DIR%sad_generator\static\index.html" (
    echo %RED%   ERROR: the sad_generator folder is missing next to the script.%RESET%
    pause
    exit /b 1
)
echo   %GREEN%✓%RESET% Found: %DIM%%SCRIPT_PATH%%RESET%

REM ── Step 3: Create build venv ────────────────────────────────
echo.
echo %BOLD%[3/6]%RESET% %CYAN%Creating build virtual environment...%RESET%

if exist "%VENV_PYTHON%" (
    echo   %DIM%Reusing build venv%RESET%
) else (
    !PY_CMD! -m venv "%VENV_DIR%" >nul 2>&1
    if not exist "%VENV_PYTHON%" (
        echo %RED%   ERROR: Failed to create venv.%RESET%
        pause
        exit /b 1
    )
    echo   %GREEN%✓%RESET% Created %DIM%%VENV_DIR%%RESET%
)

REM ── Step 4: Install build dependencies ───────────────────────
echo.
echo %BOLD%[4/6]%RESET% %CYAN%Installing app + build dependencies...%RESET%
echo   %DIM%This installs fastapi, uvicorn, xlrd, xlwt, openpyxl, httpx, bs4,%RESET%
echo   %DIM%python-multipart, and pyinstaller. May take a few minutes.%RESET%
echo.

"%VENV_PYTHON%" -m pip install --upgrade pip >nul 2>&1
"%VENV_PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements.txt" pyinstaller

if %errorlevel% neq 0 (
    echo.
    echo %RED%   ERROR: Dependency installation failed.%RESET%
    echo %YELLOW%   Check your internet connection and try again.%RESET%
    pause
    exit /b 1
)
echo   %GREEN%✓%RESET% Dependencies installed.

REM ── Step 5: Run PyInstaller ──────────────────────────────────
echo.
echo %BOLD%[5/6]%RESET% %CYAN%Building .exe with PyInstaller...%RESET%
echo   %DIM%This bundles Python + all deps + your script into one .exe.%RESET%
echo   %DIM%First build is slow (~2-3 min). Subsequent builds are faster.%RESET%
echo.

REM ── Clean previous build artifacts ──
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%" 2>nul
if exist "%EXE_PATH%" del /q "%EXE_PATH%" 2>nul

pushd "%SCRIPT_DIR%"
"%VENV_PYTHON%" -m PyInstaller --clean --noconfirm "%SPEC_FILE%"
set "BUILD_RC=%errorlevel%"
popd

if %BUILD_RC% neq 0 (
    echo.
    echo %RED%   ERROR: PyInstaller build failed.%RESET%
    echo %YELLOW%   See the output above for details.%RESET%
    pause
    exit /b 1
)

echo   %GREEN%✓%RESET% Build complete.

REM ── Step 6: Verify output ────────────────────────────────────
echo.
echo %BOLD%[6/6]%RESET% %CYAN%Verifying output...%RESET%

if not exist "%EXE_PATH%" (
    echo %RED%   ERROR: Expected .exe not found at:%RESET%
    echo %BOLD%     %EXE_PATH%%RESET%
    pause
    exit /b 1
)

for %%I in ("%EXE_PATH%") do set "EXE_SIZE_MB=%%~zI"
set /a EXE_SIZE_MB=!EXE_SIZE_MB! / 1048576

echo   %GREEN%✓%RESET% Output: %DIM%%EXE_PATH%%RESET%
echo   %GREEN%✓%RESET% Size:   %BOLD%!EXE_SIZE_MB! MB%RESET%

REM ── Cleanup build artifacts ──
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%" 2>nul

echo.
echo %DIM%──────────────────────────────────────────────────────────────%RESET%
echo.
echo %GREEN%   ✓ BUILD SUCCESSFUL%RESET%
echo.
echo %BOLD%   Your standalone .exe is ready:%RESET%
echo %BOLD%     %EXE_PATH%%RESET%
echo.
echo %DIM%   To distribute:%RESET%
echo %DIM%     1. Copy ASYCUDA_SAD_Generator.exe to any Windows machine%RESET%
echo %DIM%     2. Double-click to run (no Python install needed)%RESET%
echo %DIM%     3. The browser opens http://localhost:8000 automatically%RESET%
echo.
echo %DIM%   Note: First launch of the .exe takes ~5-10 seconds%RESET%
echo %DIM%   (it unpacks to a temp folder). After that, it's fast.%RESET%
echo.
echo %DIM%   Generated SAD files are saved to:%RESET%
echo %DIM%     .\sad_output\ (next to the .exe)%RESET%
echo.
pause
endlocal
