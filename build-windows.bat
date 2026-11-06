@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1

set "PYINSTALLER_CONFIG_DIR=%CD%\build\pyinstaller-cache"
set "MPLCONFIGDIR=%CD%\build\matplotlib-cache"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm PaperReader-windows.spec
if errorlevel 1 exit /b 1

set "QT_QPA_PLATFORM=offscreen"
"dist\PaperReader\PaperReader.exe" --smoke-test
if errorlevel 1 exit /b 1

powershell -NoProfile -Command "Compress-Archive -Path 'dist\PaperReader' -DestinationPath 'dist\PaperReader-Windows-x64.zip' -Force"
if errorlevel 1 exit /b 1

echo Build complete: dist\PaperReader-Windows-x64.zip
exit /b 0
