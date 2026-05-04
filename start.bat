@echo off
title Learner Tracking Auto-Start
echo Starting server...
start /B python app.py
timeout /t 3 /nobreak >nul
echo Opening Chrome with auto-login for %USERNAME%...
start chrome "http://MELHS-CGM04VM5G:5000/auto_login?username=%USERNAME%"
