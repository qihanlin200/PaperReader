@echo off
cd /d "%~dp0"
rem Module startup restarts existing instances from this project only.
.venv\Scripts\python.exe -m paperreader
if errorlevel 1 pause
