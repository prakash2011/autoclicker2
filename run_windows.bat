@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Antigravity Auto-Submit (Windows)
cd /d "%~dp0"

echo ========================================================
echo   Antigravity Auto-Submit Tool (Windows 10 / 11)
echo ========================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

REM Fast check for dependencies; only run pip if any are missing
python -c "import cv2, numpy, mss, PIL" >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/2] Installing dependencies...
    pip install -r requirements.txt --quiet
) else (
    echo [1/2] Dependencies already satisfied.
)

echo [2/2] Launching Auto-Submit...
echo.

REM If arguments were passed, forward them; otherwise run default continuous monitor
if "%~1"=="" (
    echo Monitoring screen for Antigravity "Submit" button...
    echo (Press Ctrl+C to stop)
    echo.
    python auto_submit_universal.py run
    pause
) else (
    python auto_submit_universal.py %*
)
