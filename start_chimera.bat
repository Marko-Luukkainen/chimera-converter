@echo off
title CHIMERA
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.bun\bin;%USERPROFILE%\.cargo\bin;%PATH%"
echo CHIMERA starts at http://127.0.0.1:5317 - close this window to stop it.
start "" cmd /c "timeout /t 8 /nobreak >nul & start http://127.0.0.1:5317"
where cargo >nul 2>nul
if %ERRORLEVEL%==0 (
  bun run dev
) else (
  echo Rust is not installed: using the prebuilt engine src\wasm\chimera.wasm
  bunx vite --host 127.0.0.1
)
pause
