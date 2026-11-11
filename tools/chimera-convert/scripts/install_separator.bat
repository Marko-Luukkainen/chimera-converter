@echo off
title chimera-convert: RoFormer separator
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_separator.ps1" %*
echo.
echo Done - you can close this window.
pause
