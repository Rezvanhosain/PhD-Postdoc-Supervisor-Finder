' No-flash shim for the desktop icon. Its only job is to run launch_app.ps1
' completely hidden (window style 0), so the user never sees a console window.
' All real launcher logic lives in launch_app.ps1, which uses a proxy-immune
' TCP readiness test - see the comments there. Keep this file tiny: anything
' that can fail belongs in the PowerShell script where it gets logged.
Option Explicit
Dim fso, shell, scriptDir, ps1, cmd, q
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = scriptDir & "\launch_app.ps1"
q = Chr(34)
cmd = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & q & ps1 & q
shell.Run cmd, 0, False
