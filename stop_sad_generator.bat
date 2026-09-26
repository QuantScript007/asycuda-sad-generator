@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title ASYCUDA SAD Generator - Stop Server

REM ─────────────────────────────────────────────────────────────
REM  ASYCUDA SAD Generator - Stop Server
REM  Finds and gracefully stops any running SAD generator server
REM ─────────────────────────────────────────────────────────────

for /f %%a in ('echo prompt $E^| cmd') do set "ESC=%%a"
set "RESET=%ESC%[0m"
set "BOLD=%ESC%[1m"
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
echo %BOLD%            Stop SAD Generator Server%RESET%
echo.

REM ── Find Python processes running sad_generator_local.py ──
echo %CYAN%Looking for running SAD generator processes...%RESET%
echo.

set "FOUND=0"

REM ── Method 1: look for python.exe with our script in command line ──
for /f "tokens=2" %%p in ('tasklist /v /fo csv ^| findstr /i "sad_generator_local" 2^>nul') do (
    set "PID=%%~p"
    set "PID=!PID:"=!"
    if not "!PID!"=="" (
        echo   %YELLOW%!%RESET% Found PID !PID! — terminating...
        taskkill /pid !PID! /f >nul 2>&1
        if !errorlevel!==0 (
            echo   %GREEN%✓%RESET% PID !PID! terminated.
            set "FOUND=1"
        )
    )
)

REM ── Method 2: any process listening on port 8000 ──
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    set "PID=%%a"
    if not "!PID!"=="0" if not "!PID!"=="" (
        echo   %YELLOW%!%RESET% Found process on port 8000 (PID !PID!) — terminating...
        taskkill /pid !PID! /f >nul 2>&1
        if !errorlevel!==0 (
            echo   %GREEN%✓%RESET% PID !PID! terminated.
            set "FOUND=1"
        )
    )
)

echo.
if !FOUND!==0 (
    echo %GREEN%   ✓ No running SAD generator processes found.%RESET%
    echo %DIM%   The server is not currently running.%RESET%
) else (
    echo %GREEN%   ✓ All SAD generator processes stopped.%RESET%
)

echo.
echo %DIM%   Note: Any browser tabs pointing to http://localhost:8000%RESET%
echo %DIM%   will show "connection refused" until you restart the server.%RESET%
echo.
pause
endlocal
