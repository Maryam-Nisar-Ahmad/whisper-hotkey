@echo off
echo Starting Whisper Hotkey...
echo On CPU, Whisper can take several minutes to load the first time. The window will show progress. After that, loads are faster.
echo.
set PATH=%PATH%;C:\Users\<user>\AppData\Local\Microsoft\WinGet\Links
cd C:\path\to\whisper-hotkey
python -u main.py
pause
