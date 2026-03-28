@echo off
cd /d "%~dp0"
echo Starting Whisper Hotkey...
echo On CPU, Whisper can take several minutes to load the first time. The window will show progress. After that, loads are faster.
echo.
python -u main.py
pause
