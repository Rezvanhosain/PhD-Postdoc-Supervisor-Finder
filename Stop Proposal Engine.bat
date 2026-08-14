@echo off
setlocal enableextensions
title Stop Proposal Engine
cd /d "%~dp0"

set "PIDFILE=.proposal_engine_app.pid"

if not exist "%PIDFILE%" (
  echo No running app found ^(%PIDFILE% missing^). Nothing to stop.
  timeout /t 2 >nul
  exit /b 0
)

rem Read only the first line (the PID). The launcher writes: PID on line 1, port on line 2.
set "PID="
for /f "usebackq delims=" %%L in ("%PIDFILE%") do if not defined PID set "PID=%%L"

if "%PID%"=="" (
  echo PID file was empty. Removing it.
  del "%PIDFILE%" >nul 2>nul
  exit /b 0
)

echo Stopping Proposal Engine ^(PID %PID%^) ...
rem Targets ONLY this PID and its own child processes — never unrelated Python.
taskkill /PID %PID% /T /F
del "%PIDFILE%" >nul 2>nul
echo Done.
timeout /t 2 >nul
endlocal
