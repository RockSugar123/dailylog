@echo off
rem Safe packaging: PyInstaller onedir wipes its output dir, so NEVER build
rem directly into the deploy target. Build to a temp dir first, then mirror.
rem Runtime data lives in %LOCALAPPDATA%\dailylog (core/config.py DATA_DIR),
rem NOT next to the exe, so the mirror needs no data-exclusion list.
setlocal
cd /d "%~dp0"

rem Deploy outside the repo: dev tree stays clean, builds can never touch sources/data
set "DEPLOY_DIR=%~dp0..\dailylog-app"

python -m PyInstaller dailylog.spec --noconfirm --distpath dist_build
if errorlevel 1 (
    echo BUILD FAILED - nothing deployed
    exit /b 1
)

robocopy dist_build\dailylog "%DEPLOY_DIR%" /MIR /NJH
if errorlevel 8 (
    echo ROBCOPY FAILED - keeping dist_build for inspection
    exit /b 1
)

rmdir /s /q dist_build
echo DONE: deployed to %DEPLOY_DIR%
