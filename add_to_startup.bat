@echo off
title Add to Startup
echo Adding Learner Tracking to Windows startup...

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set TARGET=D:\Sripts\Leaner tracking\start.bat
set DEST=%STARTUP%\LearnerTracking.bat

copy /Y "%TARGET%" "%DEST%"

if exist "%DEST%" (
    echo Done! Learner Tracking will now start automatically on login.
) else (
    echo Failed to copy start.bat. Try running as Administrator.
)
pause
