@echo off
title Add Student to Startup
echo Copying Start Student to All Users Startup...

set SOURCE=%~dp0start STUDENT.bat
set DEST=C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\LearnerTrackingStudent.bat

copy /Y "%SOURCE%" "%DEST%"

if exist "%DEST%" (
    echo Done! Learner Tracking will open for all users on login.
) else (
    echo Failed to copy. Try running as Administrator.
)
pause
