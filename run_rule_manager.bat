@echo off
setlocal

set "PROJECT_DIR=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%scripts\run_rule_manager.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Khong the khoi dong phan mem Quan ly du lieu sao ke.
    pause
)

exit /b %EXIT_CODE%
