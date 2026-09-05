@echo off
setlocal
cd /d "%~dp0."
call "%~dp0build.bat"
if errorlevel 1 ( echo PYINSTALLER FAILED & exit /b 1 )
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" installer.iss
if errorlevel 1 ( echo ISCC FAILED & exit /b 1 )
echo DONE: dist\dailylog-setup-1.2.0.exe
