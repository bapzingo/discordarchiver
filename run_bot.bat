@echo off
title Discord Archiver Bot
echo Starting Discord Archiver Bot...
echo.

:: Check if python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in your PATH.
    echo Please install Python from https://python.org
    pause
    exit /b
)

:: Install requirements if they exist
if exist requirements.txt (
    echo Checking dependencies...
    pip install -r requirements.txt >nul 2>&1
)

:: Run the bot
echo Launching bot...
python bot.py

:: Keep window open if bot crashes
if %errorlevel% neq 0 (
    echo.
    echo ❌ Bot crashed or stopped unexpectedly!
    pause
) else (
    echo.
    echo Bot stopped.
    pause
)
