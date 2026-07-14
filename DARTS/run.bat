@echo off
REM DARTS launcher for Windows
REM Sets up a Python virtual environment if not already present,
REM installs dependencies, then starts darts.py.

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set VENV_DIR=%SCRIPT_DIR%.venv

REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [DARTS] Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [DARTS] ERROR: Failed to create virtual environment.
        echo         Make sure Python 3.8+ is installed and on your PATH.
        pause
        exit /b 1
    )
)

REM Activate and install/upgrade dependencies
call "%VENV_DIR%\Scripts\activate.bat"
echo [DARTS] Installing dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r "%SCRIPT_DIR%requirements.txt"

echo [DARTS] Starting DART-B core...
python "%SCRIPT_DIR%darts.py" %*
