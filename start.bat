@echo off
title Learner Tracking Auto-Start
setlocal
echo Starting server...
set "APP_DIR=%~dp0"

set "PORTABLE_PYTHON=%APP_DIR%python\python.exe"
set "PYTHON_EXE="
set "BOOTSTRAP_PYTHON="

if exist "%PORTABLE_PYTHON%" (
    set "PYTHON_EXE=%PORTABLE_PYTHON%"
)

if not defined PYTHON_EXE if exist "%APP_DIR%.venv\Scripts\python.exe" (
    "%APP_DIR%.venv\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"
)

if not defined PYTHON_EXE if exist "%APP_DIR%.venv-1\Scripts\python.exe" (
    "%APP_DIR%.venv-1\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=%APP_DIR%.venv-1\Scripts\python.exe"
)

if defined PYTHON_EXE (
    rem Use the working interpreter found above.
) else (
    where py >nul 2>&1 && set "BOOTSTRAP_PYTHON=py -3"
    if not defined BOOTSTRAP_PYTHON (
        where python >nul 2>&1 && set "BOOTSTRAP_PYTHON=python"
    )
    if not defined BOOTSTRAP_PYTHON (
        echo No usable Python runtime found.
        echo.
        echo Option 1:
        echo   Put a portable interpreter at "%PORTABLE_PYTHON%"
        echo.
        echo Option 2:
        echo   Install Python and ensure "py" or "python" is on PATH.
        pause
        exit /b 1
    )

    echo Creating local virtual environment...
    call %BOOTSTRAP_PYTHON% -m venv "%APP_DIR%.venv"
    if errorlevel 1 (
        echo Failed to create .venv
        pause
        exit /b 1
    )

    set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"
    echo Installing requirements...
    call "%PYTHON_EXE%" -m pip install --upgrade pip >nul
    call "%PYTHON_EXE%" -m pip install -r "%APP_DIR%requirements.txt"
    if errorlevel 1 (
        echo Failed to install requirements.
        pause
        exit /b 1
    )
)

start /B "" "%PYTHON_EXE%" "%APP_DIR%app.py"
timeout /t 3 /nobreak >nul
echo Opening Chrome minimized with auto-login for %USERNAME%...
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process 'chrome' -ArgumentList '--new-window','--start-minimized','http://localhost:5000/auto_login?username=%USERNAME%'"
timeout /t 2 /nobreak >nul
endlocal
