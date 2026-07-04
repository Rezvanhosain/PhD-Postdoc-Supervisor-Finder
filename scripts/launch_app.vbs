' Desktop-icon launcher. Runs completely windowless (like pythonw.exe), but
' unlike a bare pythonw shortcut it: reuses an already-running server instead
' of starting a second copy, waits for the server to actually come up before
' opening the browser, and shows a real error dialog if startup fails.
Option Explicit

Dim fso, shell, scriptDir, repoRoot, pythonwPath, appUrl, i, ok

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)
pythonwPath = repoRoot & "\.venv\Scripts\pythonw.exe"
appUrl = "http://127.0.0.1:8765/"

Function ServerIsUp()
    Dim http
    ServerIsUp = False
    On Error Resume Next
    Set http = Nothing
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    If Not (http Is Nothing) Then
        http.SetTimeouts 1000, 1000, 1500, 1500
        http.Open "GET", appUrl, False
        http.Send
        If Err.Number = 0 And http.Status = 200 Then
            ServerIsUp = True
        End If
    End If
    Err.Clear
    On Error Goto 0
End Function

If Not fso.FileExists(pythonwPath) Then
    MsgBox "Setup looks incomplete." & vbCrLf & vbCrLf & _
           pythonwPath & vbCrLf & "was not found." & vbCrLf & vbCrLf & _
           "Please run scripts\install_windows.bat first, then try the " & _
           "desktop icon again.", vbCritical, "PhD Supervisor Finder"
    WScript.Quit 1
End If

' Already running from a previous launch: just (re)open the browser.
If ServerIsUp() Then
    shell.Run appUrl, 1, False
    WScript.Quit 0
End If

' Start the app hidden (window style 0 = no window), from the repo root.
shell.CurrentDirectory = repoRoot
shell.Run """" & pythonwPath & """ -m app.main", 0, False

' Wait for the local server to come up (up to ~30 seconds).
ok = False
For i = 1 To 30
    WScript.Sleep 1000
    If ServerIsUp() Then
        ok = True
        Exit For
    End If
Next

If ok Then
    shell.Run appUrl, 1, False
Else
    MsgBox "The app did not start within 30 seconds." & vbCrLf & vbCrLf & _
           "Check the log file for details:" & vbCrLf & _
           "%USERPROFILE%\.phd_finder\app.log" & vbCrLf & vbCrLf & _
           "You can also run scripts\run_windows.bat to see the error " & _
           "directly in a console window.", _
           vbExclamation, "PhD Supervisor Finder - startup problem"
    WScript.Quit 1
End If
