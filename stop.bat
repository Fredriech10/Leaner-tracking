@echo off
title Stop Learner Tracking Server
echo Stopping server...
taskkill /F /FI "WINDOWTITLE eq Learner Tracking Server" /T >nul 2>&1
taskkill /F /IM py.exe /FI "MEMUSAGE gt 1" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Server stopped.
timeout /t 2 /nobreak >nul
