# Real desktop-icon launcher logic. Invoked hidden by launch_app.vbs so there
# is no console flash. Uses a raw TCP connect for readiness detection, which -
# unlike an HTTP probe through WinHttp/WinINet - is completely immune to the
# Windows proxy / WPAD auto-detect stack. An HTTP probe was previously giving
# intermittent false "server is up" results for a dead local port, which made
# the launcher open the browser without ever starting the app.
$ErrorActionPreference = 'Stop'

$root       = Split-Path -Parent $PSScriptRoot
$pythonw    = Join-Path $root '.venv\Scripts\pythonw.exe'
$logFile    = Join-Path $root '.venv\launch_output.log'
$appUrl     = 'http://127.0.0.1:8765/'
$appHost    = '127.0.0.1'
$appPort    = 8765

function Test-Port {
    # Proxy-immune TCP connect test with a short timeout.
    param([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 1000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false) -and $client.Connected) {
            $client.EndConnect($iar)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Show-Error([string]$msg) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $msg, 'PhD Supervisor Finder - startup problem',
        'OK', 'Warning') | Out-Null
}

if (-not (Test-Path $pythonw)) {
    Show-Error ("Setup looks incomplete.`n`n$pythonw`nwas not found.`n`n" +
        "Please run scripts\install_windows.bat first, then try the desktop icon again.")
    exit 1
}

# Already running? Just open the browser and stop.
if (Test-Port -TargetHost $appHost -Port $appPort) {
    Start-Process $appUrl
    exit 0
}

# Start the app hidden, from the repo root, with all output captured to a log.
# pythonw.exe has no console, so without redirected stdout/stderr the first
# print() (NiceGUI prints "ready to go") would crash it silently; the log both
# prevents that and records any real startup error.
Start-Process -FilePath $pythonw -ArgumentList '-m', 'app.main' `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err')

# Wait (up to ~30s) for the port to actually accept connections.
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Port -TargetHost $appHost -Port $appPort) { $ready = $true; break }
}

if ($ready) {
    Start-Process $appUrl
    exit 0
} else {
    $detail = ''
    if (Test-Path $logFile) { $detail = "`n`n" + (Get-Content $logFile -Raw -ErrorAction SilentlyContinue) }
    Show-Error ("The app did not start within 30 seconds.`n`nStartup log:`n$logFile$detail")
    exit 1
}
