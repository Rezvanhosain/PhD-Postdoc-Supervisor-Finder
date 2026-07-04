# Real desktop-icon launcher logic. Invoked hidden by launch_app.vbs so there
# is no console flash.
#
# Two things matter for a reliable "no Connection lost" launch:
#
#  1. Readiness is confirmed with a real HTTP 200 over a RAW SOCKET (Test-Http
#     below), not just a TCP accept. uvicorn accepts the TCP connection at the
#     socket level slightly before the ASGI app (and NiceGUI's websocket route)
#     is ready to serve. Opening the browser during that window makes the page
#     load but the socket.io websocket fail -> "Connection lost. Trying to
#     reconnect...". A raw-socket GET is also immune to the Windows proxy/WPAD
#     stack (an HTTP probe through WinHttp/WinINet gave false results earlier).
#
#  2. The launcher OWNS browser-opening. It sets PPSF_NO_SHOW=1 so the app does
#     not also auto-open a browser (NiceGUI's show=True fires the instant the
#     server prints "ready", before websockets are reliably up, and produced a
#     second, broken "Connection lost" tab). One tab, opened at the right time.
$ErrorActionPreference = 'Stop'

$root       = Split-Path -Parent $PSScriptRoot
$pythonw    = Join-Path $root '.venv\Scripts\pythonw.exe'
$logFile    = Join-Path $root '.venv\launch_output.log'
$appUrl     = 'http://127.0.0.1:8765/'
$appHost    = '127.0.0.1'
$appPort    = 8765

function Test-Http {
    # Proxy-immune HTTP readiness check: connect a raw socket, send a minimal
    # GET, and confirm the status line says 200. Returns $true only when the
    # ASGI app is actually serving requests.
    param([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 1500)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) -or -not $client.Connected) {
            return $false
        }
        $client.EndConnect($iar)
        $client.ReceiveTimeout = $TimeoutMs
        $client.SendTimeout = $TimeoutMs
        $stream = $client.GetStream()
        $req = "GET / HTTP/1.0`r`nHost: $TargetHost`r`nConnection: close`r`n`r`n"
        $bytes = [System.Text.Encoding]::ASCII.GetBytes($req)
        $stream.Write($bytes, 0, $bytes.Length)
        $buf = New-Object byte[] 256
        $n = $stream.Read($buf, 0, $buf.Length)
        $head = [System.Text.Encoding]::ASCII.GetString($buf, 0, $n)
        return ($head -match '^HTTP/1\.[01]\s+200')
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Open-Browser([string]$url) {
    # Never let a browser-open hiccup abort the launcher; the app is already
    # running by this point, so a failure here is cosmetic.
    try { Start-Process $url } catch { }
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

# Already running and serving? Just open the browser and stop.
if (Test-Http -TargetHost $appHost -Port $appPort) {
    Open-Browser $appUrl
    exit 0
}

# Start the app hidden, from the repo root, with all output captured to a log.
# pythonw.exe has no console, so without redirected stdout/stderr the first
# print() (NiceGUI prints "ready to go") would crash it silently; the log both
# prevents that and records any real startup error. PPSF_NO_SHOW=1 stops the
# app from auto-opening its own (racy) browser tab - this launcher opens it.
$env:PPSF_NO_SHOW = '1'
Start-Process -FilePath $pythonw -ArgumentList '-m', 'app.main' `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err')

# Wait (up to ~40s) for the app to actually serve HTTP 200, then a short settle
# so the websocket route is fully live before the browser connects.
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Http -TargetHost $appHost -Port $appPort) { $ready = $true; break }
}

if ($ready) {
    Start-Sleep -Milliseconds 750
    Open-Browser $appUrl
    exit 0
} else {
    $detail = ''
    if (Test-Path $logFile) { $detail = "`n`n" + (Get-Content $logFile -Raw -ErrorAction SilentlyContinue) }
    Show-Error ("The app did not start within 40 seconds.`n`nStartup log:`n$logFile$detail")
    exit 1
}
