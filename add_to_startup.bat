@echo off
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "OUT=%STARTUP%\whisper-hotkey.vbs"
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = "%REPO%"
echo WshShell.Run chr^(34^) ^& "%REPO%\run.bat" ^& chr^(34^), 0, False
) > "%OUT%"
echo Created: %OUT%
echo Points to: %REPO%
pause
