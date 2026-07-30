@echo off
title Learner Tracking
echo %USERNAME% | findstr /I /B "MELHS" >nul && exit /b
echo Opening Learner Tracking for %USERNAME%...
powershell -Command "Start-Process 'chrome' -ArgumentList 'http://%COMPUTERNAME%:5000/auto_login?username=%USERNAME%^&attendance=lab^&pc=%COMPUTERNAME%' -WindowStyle Minimized"
