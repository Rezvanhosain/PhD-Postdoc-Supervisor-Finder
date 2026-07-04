# Creates a Desktop shortcut that launches the app without a visible terminal.
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop 'PhD Supervisor Finder.lnk'

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($shortcut)
$sc.TargetPath = Join-Path $root '.venv\Scripts\pythonw.exe'
$sc.Arguments = '-m app.main'
$sc.WorkingDirectory = $root
$icon = Join-Path $root 'assets\app.ico'
if (Test-Path $icon) { $sc.IconLocation = $icon }
$sc.Description = 'PhD & Postdoc Supervisor Finder'
$sc.Save()
Write-Host "Shortcut created: $shortcut"
