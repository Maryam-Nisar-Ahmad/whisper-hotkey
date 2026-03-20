Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "C:\path\to\whisper-hotkey\run.bat" & chr(34), 0
Set WshShell = Nothing
