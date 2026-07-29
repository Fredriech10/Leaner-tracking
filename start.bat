@echo off
title Learner Tracking Auto-Start
echo Starting server...
start "" /B "%~dp0venv\Scripts\python.exe" "%~dp0app.py"
timeout /t 3 /nobreak >nul
echo Opening Chrome with auto-login for %USERNAME%...
start chrome "http://%COMPUTERNAME%:5000/auto_login?username=%USERNAME%^&attendance=lab^&pc=%COMPUTERNAME%"
