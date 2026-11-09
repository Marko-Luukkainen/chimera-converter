@echo off
title chimera-convert install
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
echo Valmis - voit sulkea taman ikkunan.
pause
