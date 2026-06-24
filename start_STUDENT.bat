@echo off
title Learner Tracking
if /I "%USERNAME:~0,5%"=="MELHS" exit /b
echo Opening Learner Tracking for %USERNAME%...
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process 'chrome' -ArgumentList '--new-window','--start-minimized','http://MELHS-CGM04VM5G:5000/auto_login?username=%USERNAME%'"
timeout /t 2 /nobreak >nul
powershell -NoProfile -WindowStyle Hidden -Command "(New-Object -ComObject Shell.Application).MinimizeAll()"
