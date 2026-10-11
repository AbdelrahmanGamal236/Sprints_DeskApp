@echo off
REM Starts the DeskApp workstation client.
set "HERE=%~dp0"
cd /d "%HERE%"
if exist "%HERE%DeskApp.exe" (
    start "" "%HERE%DeskApp.exe" %*
) else if exist "%HERE%dist\DeskApp\DeskApp.exe" (
    start "" "%HERE%dist\DeskApp\DeskApp.exe" %*
) else (
    start "" pythonw.exe "%HERE%main.py" %*
)
