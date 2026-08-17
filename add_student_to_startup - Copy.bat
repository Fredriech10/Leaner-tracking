@echo off
title Add Student to Startup

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Copying Start Student to All Users Startup...

set SOURCE=%~dp0WCGSCHOOLSProxyFIX ON.bat
set DEST=C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\ProxyON.bat

copy /Y "%SOURCE%" "%DEST%"

if exist "%DEST%" (
    echo Done! Learner Tracking will open for all users on login.
) else (
    echo Failed to copy.
)
pause
