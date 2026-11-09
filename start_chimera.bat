@echo off
title CHIMERA
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.bun\bin;%USERPROFILE%\.cargo\bin;%PATH%"
echo CHIMERA kaynnistyy osoitteeseen http://127.0.0.1:5317 - sulje tama ikkuna lopettaaksesi.
start "" cmd /c "timeout /t 8 /nobreak >nul & start http://127.0.0.1:5317"
where cargo >nul 2>nul
if %ERRORLEVEL%==0 (
  bun run dev
) else (
  echo Rustia ei ole asennettu: kaytetaan valmiiksi kaannettya moottoria src\wasm\chimera.wasm
  bunx vite --host 127.0.0.1
)
pause
