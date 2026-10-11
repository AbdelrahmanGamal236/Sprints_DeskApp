@echo off
REM Starts the DeskApp Central Server. Keep this window open while people use DeskApp.
set "HERE=%~dp0"
cd /d "%HERE%"
title DeskApp Central Server
if exist "%HERE%DeskAppServer.exe" (
    "%HERE%DeskAppServer.exe" %*
) else if exist "%HERE%dist\DeskApp\DeskAppServer.exe" (
    "%HERE%dist\DeskApp\DeskAppServer.exe" %*
) else (
    python.exe "%HERE%main.py" --server-only %*
)
echo.
echo The Central Server has stopped.
pause
