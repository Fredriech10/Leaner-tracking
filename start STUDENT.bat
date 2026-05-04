@echo off
title Learner Tracking
echo Opening Learner Tracking for %USERNAME%...
start chrome "http://MELHS-CGM04VM5G:5000/auto_login?username=%USERNAME%"
