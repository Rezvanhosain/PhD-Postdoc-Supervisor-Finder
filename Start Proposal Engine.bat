@echo off
setlocal enableextensions
title Proposal Engine (local)
cd /d "%~dp0"

rem --- Pick a Python: prefer a local .venv, else system python ---------------
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

rem If no .venv and python is missing, create a local venv.
if not exist ".venv\Scripts\python.exe" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python was not found on PATH. Install Python 3.11+ and retry.
    pause
    exit /b 1
  )
)

rem --- Install requirements ONLY if something is missing ---------------------
"%PY%" -c "import fastapi, uvicorn, multipart, proposal_engine" 1>nul 2>nul
if errorlevel 1 (
  echo Installing required packages ^(first run only^)...
  "%PY%" -m pip install -r requirements.txt
)

rem --- Start the local app (loads .env automatically, opens the browser) -----
echo.
echo Starting Proposal Engine on http://127.0.0.1:8765 (or next free port) ...
echo The browser opens automatically at the exact URL printed just below.
echo Keep this window open. Use "Stop Local App" in the browser, or close it.
echo.
"%PY%" -m desktop_app

endlocal
