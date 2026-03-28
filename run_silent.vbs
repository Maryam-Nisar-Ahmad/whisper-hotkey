' Runs run.bat from this repo folder (same directory as this .vbs file).
Dim sh, fso, dir
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
sh.Run Chr(34) & dir & "\run.bat" & Chr(34), 0, False
Set sh = Nothing
Set fso = Nothing
