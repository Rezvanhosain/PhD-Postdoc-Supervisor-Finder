@echo off
REM One-time installer: creates a venv, installs dependencies, and puts a
REM desktop shortcut on your Desktop. Requires Python 3.10+ from python.org.
REM Safe to re-run: a partial or locked .venv from a previous attempt is
REM detected and rebuilt automatically - no manual cleanup needed.
setlocal
cd /d "%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_venv.ps1"
if errorlevel 1 (
    echo.
    echo Setup failed - see the message above for what to do next.
    pause
    exit /b 1
)

echo Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1

echo.
echo Done! Launch "PhD Supervisor Finder" from your Desktop.
pause
