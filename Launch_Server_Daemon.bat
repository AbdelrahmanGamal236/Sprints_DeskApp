@echo off
title Central Server Daemon - Offline Task Manager
if exist "dist\DeskApp\DeskApp.exe" (
    echo Starting Central Server via Compiled Executable...
    "dist\DeskApp\DeskApp.exe" --server-only
) else if exist "DeskApp.exe" (
    echo Starting Central Server via Local Executable...
    DeskApp.exe --server-only
) else (
    echo Starting Central Server via Python...
    python.exe main.py --server-only
)
pause
