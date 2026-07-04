' Desktop-icon launcher. Runs completely windowless (like pythonw.exe), but
' unlike a bare pythonw shortcut it: reuses an already-running server instead
' of starting a second copy, waits for the server to actually come up before
' opening the browser, and shows a real error dialog (with a log file path)
' if startup fails.
'
' IMPORTANT: pythonw.exe has no console, so with no stdout/stderr
' redirection sys.stdout/sys.stderr are None. Any print() call anywhere in
' the app or its dependencies (NiceGUI itself prints "ready to go" on
' startup) then raises an unhandled AttributeError and kills the process
' within a second of starting - silently, since there is no console to show
' it. To avoid this, the app is launched through a hidden cmd.exe that
' redirects both streams to a real log file.
Option Explicit

Dim fso, shell, scriptDir, repoRoot, pythonwPath, appUrl, logFile, i, ok

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)
pythonwPath = repoRoot & "\.venv\Scripts\pythonw.exe"
appUrl = "http://127.0.0.1:8765/"
logFile = repoRoot & "\.venv\launch_output.log"

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

' Start the app hidden, from the repo root, with stdout/stderr redirected to
' a log file (see note above - this is required, not optional, under
' pythonw.exe). Routed through cmd.exe /c since WScript.Shell.Run has no
' native redirection support. Chr(34) is used instead of doubled quotes to
' keep the quoting unambiguous.
Dim q, launchCmd
q = Chr(34)
launchCmd = "cmd /c " & q & pythonwPath & q & " -m app.main > " & q & logFile & q & " 2>&1"
shell.CurrentDirectory = repoRoot
shell.Run launchCmd, 0, False

' Wait for the local server to come up (up to ~30 seconds), then double-check
' a moment later in case it crashed right after answering the first probe.
ok = False
For i = 1 To 30
    WScript.Sleep 1000
    If ServerIsUp() Then
        WScript.Sleep 1000
        ok = ServerIsUp()
        Exit For
    End If
Next

If ok Then
    shell.Run appUrl, 1, False
Else
    MsgBox "The app did not start correctly." & vbCrLf & vbCrLf & _
           "Check the startup log for the exact error:" & vbCrLf & _
           logFile & vbCrLf & vbCrLf & _
           "You can also run scripts\run_windows.bat to see the error " & _
           "directly in a console window.", _
           vbExclamation, "PhD Supervisor Finder - startup problem"
    WScript.Quit 1
End If
