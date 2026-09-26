@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title ASYCUDA SAD Generator - Local Edition

REM ─────────────────────────────────────────────────────────────
REM  ASYCUDA SAD Generator - Windows Launcher
REM  - Checks Python is installed
REM  - Creates/uses a virtual environment
REM  - Installs dependencies if missing
REM  - Launches the server and opens the browser
REM ─────────────────────────────────────────────────────────────

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%sad_generator_local.py"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "REQUIREMENTS=%SCRIPT_DIR%requirements.txt"

REM ── Colors via ANSI escape codes (Win 10+ supports them) ──
for /f %%a in ('echo prompt $E^| cmd') do set "ESC=%%a"
set "RESET=%ESC%[0m"
set "BOLD=%ESC%[1m"
set "DIM=%ESC%[2m"
set "GREEN=%ESC%[32m"
set "YELLOW=%ESC%[33m"
set "BLUE=%ESC%[34m"
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
echo %BOLD%            ASYCUDA SAD Generator - Local Edition%RESET%
echo %DIM%            Runs entirely on your machine, no internet credits needed.%RESET%
echo.
echo %DIM%──────────────────────────────────────────────────────────────%RESET%
echo.

REM ── Step 1: Locate Python ────────────────────────────────────
echo %BOLD%[1/5]%RESET% %CYAN%Checking Python installation...%RESET%

where python >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=python"
    goto :python_found
)

where py >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=py -3"
    goto :python_found
)

echo.
echo %RED%   ERROR: Python was not found on your system.%RESET%
echo.
echo %YELLOW%   Please install Python 3.10+ from:%RESET%
echo %BOLD%     https://www.python.org/downloads/windows/%RESET%
echo.
echo %YELLOW%   During installation, make sure to check:%RESET%
echo %BOLD%     [x] Add Python to PATH%RESET%
echo.
echo %DIM%   After installing, close this window and run the .bat file again.%RESET%
echo.
pause
exit /b 1

:python_found
for /f "tokens=*" %%v in ('!PY_CMD! -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "PY_VER=%%v"
echo   %GREEN%✓%RESET% Python %BOLD%!PY_VER!%RESET% found at: %DIM%!PY_CMD!%RESET%

REM ── Check Python version >= 3.10 ──
!PY_CMD! -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if not %errorlevel%==0 (
    echo.
    echo %YELLOW%   WARNING: Python !PY_VER! is older than 3.10.%RESET%
    echo %YELLOW%   The app may still work, but 3.10+ is recommended.%RESET%
    echo.
    choice /c YN /m "   Continue anyway"
    if errorlevel 2 exit /b 1
)

REM ── Step 2: Verify script exists ─────────────────────────────
echo.
echo %BOLD%[2/5]%RESET% %CYAN%Locating application script...%RESET%

if not exist "%SCRIPT_PATH%" (
    echo.
    echo %RED%   ERROR: sad_generator_local.py was not found.%RESET%
    echo.
    echo %DIM%   Expected location:%RESET%
    echo %BOLD%     %SCRIPT_PATH%%RESET%
    echo.
    echo %YELLOW%   Please place this .bat file in the same folder as%RESET%
    echo %BOLD%     sad_generator_local.py%RESET% %YELLOW%and try again.%RESET%
    echo.
    pause
    exit /b 1
)
echo   %GREEN%✓%RESET% Found: %DIM%%SCRIPT_PATH%%RESET%

REM ── Step 3: Create virtual environment ───────────────────────
echo.
echo %BOLD%[3/5]%RESET% %CYAN%Setting up virtual environment...%RESET%

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    echo   %GREEN%✓%RESET% Reusing existing venv: %DIM%%VENV_DIR%%RESET%
) else (
    echo   %DIM%Creating fresh virtual environment...%RESET%
    !PY_CMD! -m venv "%VENV_DIR%" >nul 2>&1
    if not exist "%VENV_PYTHON%" (
        echo.
        echo %RED%   ERROR: Failed to create virtual environment.%RESET%
        echo %YELLOW%   Trying without venv...%RESET%
        set "VENV_PYTHON=!PY_CMD!"
        goto :install_deps
    )
    echo   %GREEN%✓%RESET% Created venv: %DIM%%VENV_DIR%%RESET%
)

REM ── Step 4: Install / update dependencies ────────────────────
:install_deps
echo.
echo %BOLD%[4/5]%RESET% %CYAN%Checking dependencies...%RESET%

REM ── Write requirements.txt if missing ──
if not exist "%REQUIREMENTS%" (
    echo   %DIM%Writing requirements.txt...%RESET%
    > "%REQUIREMENTS%" echo fastapi
    >> "%REQUIREMENTS%" echo uvicorn[standard]
    >> "%REQUIREMENTS%" echo xlrd==2.0.1
    >> "%REQUIREMENTS%" echo xlwt==1.3.0
    >> "%REQUIREMENTS%" echo openpyxl==3.1.5
    >> "%REQUIREMENTS%" echo httpx==0.28.1
    >> "%REQUIREMENTS%" echo beautifulsoup4==4.12.3
    >> "%REQUIREMENTS%" echo python-multipart
    echo   %GREEN%✓%RESET% Wrote %DIM%requirements.txt%RESET%
)

REM ── Check if key deps already installed in venv ──
set "NEEDS_INSTALL=0"
"%VENV_PYTHON%" -c "import fastapi, uvicorn, xlrd, xlwt, openpyxl, httpx, bs4, multipart" >nul 2>&1
if not %errorlevel%==0 set "NEEDS_INSTALL=1"

if %NEEDS_INSTALL%==1 (
    echo   %DIM%Installing dependencies (first run only, may take a minute)...%RESET%
    "%VENV_PYTHON%" -m pip install --upgrade pip >nul 2>&1
    "%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS%"
    if %errorlevel% neq 0 (
        echo.
        echo %RED%   ERROR: Dependency installation failed.%RESET%
        echo %YELLOW%   Please check your internet connection and try again.%RESET%
        echo.
        pause
        exit /b 1
    )
    echo   %GREEN%✓%RESET% Dependencies installed successfully.
) else (
    echo   %GREEN%✓%RESET% All dependencies already installed.
)

REM ── Step 5: Launch the server ────────────────────────────────
echo.
echo %BOLD%[5/5]%RESET% %CYAN%Starting ASYCUDA SAD Generator server...%RESET%
echo.
echo %DIM%──────────────────────────────────────────────────────────────%RESET%
echo.
echo   %BOLD%Web UI:%RESET%     http://localhost:8000
echo   %BOLD%API Docs:%RESET%   http://localhost:8000/docs
echo   %BOLD%Output:%RESET%     %SCRIPT_DIR%sad_output\
echo.
echo %DIM%   The browser will open automatically in a moment.%RESET%
echo %DIM%   Press Ctrl+C in this window to stop the server.%RESET%
echo.

REM ── Launch the server (opens the browser itself; blocks until Ctrl+C) ──
REM    Tip: add  --host 0.0.0.0  to let other computers on your network connect.
cd /d "%SCRIPT_DIR%"
"%VENV_PYTHON%" "%SCRIPT_PATH%" serve %*

REM ── Server stopped ──
echo.
echo %DIM%──────────────────────────────────────────────────────────────%RESET%
echo.
echo %YELLOW%   Server stopped.%RESET%
echo.
echo %DIM%   Generated SAD files are saved in:%RESET%
echo %BOLD%     %SCRIPT_DIR%sad_output\%RESET%
echo.
pause
endlocal
