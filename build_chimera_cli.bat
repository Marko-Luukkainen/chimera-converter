@echo off
title CHIMERA CLI build + test
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
echo Kaannetaan ja testataan chimera-cli ... loki: target\build-cli.log
(cargo build --release -p chimera-cli && cargo test --release -p chimera-cli) > target\build-cli.log 2>&1
echo EXIT %ERRORLEVEL% >> target\build-cli.log
