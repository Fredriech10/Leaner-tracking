@echo off
setlocal
title Learner Tracking
if /I "%USERNAME:~0,5%"=="MELHS" goto :EOF
if /I "%USERNAME%"=="ita" goto :EOF
echo Opening Learner Tracking for %USERNAME%...
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process 'chrome' -ArgumentList '--new-window','--start-minimized','http://MELHS-CGM04VM5G:5000/auto_login?username=%USERNAME%'"
timeout /t 2 /nobreak >nul
endlocal
