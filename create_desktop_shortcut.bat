@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Create Desktop Shortcut - ASYCUDA SAD Generator

REM ─────────────────────────────────────────────────────────────
REM  Creates a desktop shortcut to start_sad_generator.bat
REM  Uses PowerShell to build a proper .lnk file (with icon)
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
echo %BOLD%            Create Desktop Shortcut%RESET%
echo.

set "SCRIPT_DIR=%~dp0"
set "START_BAT=%SCRIPT_DIR%start_sad_generator.bat"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\ASYCUDA SAD Generator.lnk"

REM ── Validate start_sad_generator.bat exists ──
if not exist "%START_BAT%" (
    echo %RED%   ERROR: start_sad_generator.bat not found.%RESET%
    echo %DIM%   Expected location: %START_BAT%%RESET%
    echo.
    echo %YELLOW%   Place this .bat file in the same folder as%RESET%
    echo %BOLD%     start_sad_generator.bat%RESET% %YELLOW%and try again.%RESET%
    echo.
    pause
    exit /b 1
)

REM ── Locate desktop ──
if not exist "%DESKTOP%" (
    echo %YELLOW%   Desktop folder not found at default location.%RESET%
    echo %YELLOW%   Trying OneDrive desktop...%RESET%
    set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
)
if not exist "%DESKTOP%" (
    echo %RED%   ERROR: Could not locate your Desktop folder.%RESET%
    pause
    exit /b 1
)

echo %CYAN%   Script location:%RESET% %DIM%%START_BAT%%RESET%
echo %CYAN%   Desktop:        %RESET% %DIM%%DESKTOP%%RESET%
echo %CYAN%   Shortcut:       %RESET% %DIM%%SHORTCUT%%RESET%
echo.
echo %CYAN%   Creating shortcut...%RESET%

REM ── Use PowerShell to create the .lnk file ──
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell; " ^
  "$Shortcut = $WshShell.CreateShortcut('%SHORTCUT%'); " ^
  "$Shortcut.TargetPath = '%START_BAT%'; " ^
  "$Shortcut.WorkingDirectory = '%SCRIPT_DIR%'; " ^
  "$Shortcut.WindowStyle = 1; " ^
  "$Shortcut.Description = 'Launch ASYCUDA SAD Generator (Local Edition)'; " ^
  "$Shortcut.IconLocation = 'shell32.dll,13'; " ^
  "$Shortcut.Save()"

if %errorlevel%==0 (
    echo.
    echo %GREEN%   ✓ Shortcut created successfully!%RESET%
    echo.
    echo %DIM%   You can now double-click "ASYCUDA SAD Generator"%RESET%
    echo %DIM%   on your desktop to start the server.%RESET%
) else (
    echo.
    echo %RED%   ERROR: Failed to create shortcut.%RESET%
    echo %YELLOW%   Make sure PowerShell is available on your system.%RESET%
)

echo.
pause
endlocal
