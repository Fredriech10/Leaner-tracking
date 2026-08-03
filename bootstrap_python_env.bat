@echo off
setlocal
set "APP_DIR=%~dp0"
set "PORTABLE_PYTHON=%APP_DIR%python\python.exe"
set "BOOTSTRAP_PYTHON="

if exist "%PORTABLE_PYTHON%" (
    set "BOOTSTRAP_PYTHON=%PORTABLE_PYTHON%"
) else (
    where py >nul 2>&1 && set "BOOTSTRAP_PYTHON=py -3"
    if not defined BOOTSTRAP_PYTHON (
        where python >nul 2>&1 && set "BOOTSTRAP_PYTHON=python"
    )
)

if not defined BOOTSTRAP_PYTHON (
    echo No Python runtime found.
    echo Place a portable interpreter at "%PORTABLE_PYTHON%"
    echo or install Python and add "py" or "python" to PATH.
    exit /b 1
)

if not exist "%APP_DIR%.venv\Scripts\python.exe" (
    echo Creating .venv...
    call %BOOTSTRAP_PYTHON% -m venv "%APP_DIR%.venv"
    if errorlevel 1 exit /b 1
) else (
    echo Reusing existing .venv...
)

echo Installing requirements...
call "%APP_DIR%.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
call "%APP_DIR%.venv\Scripts\python.exe" -m pip install -r "%APP_DIR%requirements.txt"
if errorlevel 1 exit /b 1

echo Environment ready at "%APP_DIR%.venv"
endlocal
