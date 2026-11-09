@echo off
title chimera-convert smoke test
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke.ps1"
