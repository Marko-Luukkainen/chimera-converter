@echo off
title Chimera-muunnin (http://127.0.0.1:5320)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_app.ps1"
