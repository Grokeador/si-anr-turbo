@echo off
title SI-ANR-Turbo v2.0 — 1-Click AI Frame Gen Upgrader
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ was not found in PATH.
    echo Opening official Python download page...
    start https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
python si_anr_turbo.py web %*
if errorlevel 1 pause
