@echo off
title CHIMERA layout lint
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.bun\bin;%USERPROFILE%\.cargo\bin;%PATH%"
echo playwright > target\checks.log
call bunx playwright-core@1.64.1 install chromium-headless-shell >> target\checks.log 2>&1
echo INSTALL EXIT %ERRORLEVEL% >> target\checks.log
call bun run lint:layout >> target\checks.log 2>&1
echo LINT EXIT %ERRORLEVEL% >> target\checks.log
echo ALL DONE >> target\checks.log
