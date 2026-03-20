@echo off
echo ================================
echo  Installing Whisper Hotkey Tool
echo ================================
echo.
echo Installing Python packages...
pip install -r requirements.txt
echo.
echo Installing ffmpeg (required by Whisper)...
winget install --id Gyan.FFmpeg -e
echo.
echo ================================
echo  Done! Run run.bat to start.
echo ================================
pause