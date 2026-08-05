@echo off
rem Safe packaging: build to a temp dir first, then mirror-deploy into dist\dailylog.
rem PyInstaller onedir wipes the output dir, so NEVER use dist\dailylog as distpath
rem (it would delete runtime data). /MIR sync excludes all data files/dirs below.
setlocal
cd /d "%~dp0"

python -m PyInstaller dailylog.spec --noconfirm --distpath dist_build
if errorlevel 1 (
    echo BUILD FAILED - nothing deployed
    exit /b 1
)

rem Mirror exe + _internal, keep runtime data untouched
robocopy dist_build\dailylog dist\dailylog /MIR /XF .env settings.json state.json dailylog.log /XD records reports screenshots
if errorlevel 8 (
    echo ROBCOPY FAILED (code %errorlevel%)
    rmdir /s /q dist_build
    exit /b 1
)

rmdir /s /q dist_build
echo DONE: dist\dailylog updated, runtime data untouched
