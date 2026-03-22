@echo off
echo Starting Whisper Hotkey...
echo First launch takes 1-2 min to load model. After that it is instant.
echo.
set PATH=%PATH%;C:\Users\<user>\AppData\Local\Microsoft\WinGet\Links
cd C:\path\to\whisper-hotkey
python -u main.py
pause
