@echo off
title CHIMERA - asennus
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_here.ps1" %*
echo.
pause
