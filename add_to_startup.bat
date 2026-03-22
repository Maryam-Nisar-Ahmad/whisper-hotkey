@echo off
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
copy "%~dp0run_silent.vbs" "%STARTUP%\whisper-hotkey.vbs"
echo Added to startup successfully!
pause
