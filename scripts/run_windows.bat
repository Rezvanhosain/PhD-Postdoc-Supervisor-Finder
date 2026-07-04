@echo off
REM Manual launcher (the desktop shortcut uses pythonw.exe with no console).
cd /d "%~dp0.."
.venv\Scripts\python -m app.main
