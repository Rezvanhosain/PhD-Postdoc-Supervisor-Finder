# Creates a Desktop shortcut that launches the app without a visible terminal.
# The shortcut targets wscript.exe running scripts\launch_app.vbs rather than
# pythonw.exe directly: the wrapper waits for the server to come up, opens
# the browser itself, reuses an already-running instance, and shows a real
# error dialog on failure - none of which a bare pythonw shortcut can do.
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop 'PhD Supervisor Finder.lnk'
$launcher = Join-Path $root 'scripts\launch_app.vbs'
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($shortcut)
$sc.TargetPath = $wscript
$sc.Arguments = '"' + $launcher + '"'
$sc.WorkingDirectory = $root
$icon = Join-Path $root 'assets\app.ico'
if (Test-Path $icon) { $sc.IconLocation = $icon }
$sc.Description = 'PhD & Postdoc Supervisor Finder'
$sc.Save()
Write-Host "Shortcut created: $shortcut"
