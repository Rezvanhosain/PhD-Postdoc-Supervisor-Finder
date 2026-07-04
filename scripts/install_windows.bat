@echo off
REM One-time installer: creates a venv, installs dependencies, and puts a
REM desktop shortcut on your Desktop. Requires Python 3.10+ from python.org.
setlocal
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from https://python.org
    echo and tick "Add Python to PATH", then run this again.
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv .venv || (echo venv creation failed & pause & exit /b 1)

echo Installing dependencies (this can take a few minutes)...
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || (echo install failed & pause & exit /b 1)

echo Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1

echo.
echo Done! Launch "PhD Supervisor Finder" from your Desktop.
pause
