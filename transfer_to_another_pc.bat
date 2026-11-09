@echo off
title CHIMERA - transfer to another machine
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\transfer\pack.ps1" %*
echo.
pause
