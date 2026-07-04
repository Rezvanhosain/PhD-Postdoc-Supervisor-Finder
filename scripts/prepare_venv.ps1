# Creates (or repairs) the .venv used by the app. Self-heals if a previous
# run left a partial/locked virtual environment - the user never has to
# manually delete .venv.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

function Get-PythonCmd {
    foreach ($cand in @('python', 'py')) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Stop-VenvProcesses {
    # Only touches processes whose executable is inside THIS repo's .venv -
    # never system Python or unrelated venvs.
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' or Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) }
    foreach ($p in $procs) {
        Write-Host "Stopping stale process from a previous run (PID $($p.ProcessId))..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($procs) { Start-Sleep -Seconds 2 }
}

function Remove-VenvDir {
    if (-not (Test-Path $venv)) { return }
    for ($i = 1; $i -le 3; $i++) {
        try {
            Remove-Item -Recurse -Force $venv -ErrorAction Stop
            return
        } catch {
            Write-Host "Removing existing .venv (attempt $i) failed: $($_.Exception.Message)"
            Stop-VenvProcesses
            Start-Sleep -Seconds 2
        }
    }
    if (Test-Path $venv) {
        throw ".venv could not be removed. Close any running copy of the app " +
              "(check Task Manager for python.exe / pythonw.exe under $venv) and re-run the installer."
    }
}

$pythonCmd = Get-PythonCmd
if (-not $pythonCmd) {
    throw "Python was not found on PATH. Install Python 3.10+ from https://python.org and " +
          "tick 'Add Python to PATH', then run the installer again."
}

$needsCreate = $true
if (Test-Path $venvPython) {
    $cfg = Join-Path $venv 'pyvenv.cfg'
    if (Test-Path $cfg) {
        # Looks like a complete, valid venv already - reuse it.
        $needsCreate = $false
        Write-Host "Existing virtual environment looks valid - reusing it."
    } else {
        Write-Host "Existing .venv looks partial/corrupted - rebuilding it."
        Stop-VenvProcesses
        Remove-VenvDir
    }
}

if ($needsCreate) {
    Write-Host "Creating virtual environment..."
    try {
        & $pythonCmd -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "python -m venv exited with code $LASTEXITCODE" }
    } catch {
        Write-Host "Virtual environment creation failed ($($_.Exception.Message)) - " +
                   "checking for a locked/partial .venv and retrying once..."
        Stop-VenvProcesses
        Remove-VenvDir
        & $pythonCmd -m venv $venv
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the virtual environment even after cleanup. " +
                  "Make sure no antivirus is blocking $venv and that you have write " +
                  "permission to this folder, then re-run the installer."
        }
    }
}

Write-Host "Installing dependencies (this can take a few minutes)..."
& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed. Check your internet connection and re-run the installer."
}

Write-Host "Virtual environment ready."
