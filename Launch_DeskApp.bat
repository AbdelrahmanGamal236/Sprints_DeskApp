@echo off
if exist "dist\DeskApp\DeskApp.exe" (
    start "" "dist\DeskApp\DeskApp.exe"
) else (
    start "" pythonw.exe main.py
)
