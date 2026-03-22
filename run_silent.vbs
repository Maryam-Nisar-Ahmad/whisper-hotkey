Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\path\to\whisper-hotkey"
WshShell.Run chr(34) & "C:\path\to\whisper-hotkey\run.bat" & chr(34), 0, False
Set WshShell = Nothing
