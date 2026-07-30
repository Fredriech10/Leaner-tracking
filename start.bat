@echo off
title Learner Tracking Auto-Start
echo Starting server...
set "APP_DIR=%~dp0"
set "PYTHON_EXE=%APP_DIR%venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo Python environment not found at "%PYTHON_EXE%"
    pause
    exit /b 1
)
start /B "" "%PYTHON_EXE%" "%APP_DIR%app.py"
timeout /t 3 /nobreak >nul
echo Opening Chrome minimized with auto-login for %USERNAME%...
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process 'chrome' -ArgumentList '--new-window','--start-minimized','http://MELHS-CGM04VM5G:5000/auto_login?username=%USERNAME%'"
timeout /t 2 /nobreak >nul
powershell -NoProfile -WindowStyle Hidden -Command "(New-Object -ComObject Shell.Application).MinimizeAll()"
