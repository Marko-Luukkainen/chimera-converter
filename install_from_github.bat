@echo off
setlocal
title CHIMERA + converter - install from GitHub
rem Clones Chimera (with Finnish support) and the converter from GitHub and installs them.
rem Run again to update. A folder can be given: install_from_github.bat D:\chimera
set "REPO=https://github.com/Marko-Luukkainen/chimera-converter.git"
set "DEST=%USERPROFILE%\chimera-converter"
if not "%~1"=="" set "DEST=%~1"
echo.
echo Installing CHIMERA + converter in %DEST%
echo The first install downloads about 6-8 GB and takes 20-40 minutes. Windows may ask for permission.
echo.
where winget >nul 2>nul
if errorlevel 1 (
  echo winget is missing: install or update "App Installer" from the Microsoft Store and run this again.
  goto fail
)
where git >nul 2>nul
if errorlevel 1 (
  echo Installing Git ...
  winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
  set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
)
where git >nul 2>nul
if errorlevel 1 (
  echo Git did not install.
  goto fail
)
if exist "%DEST%\.git" (
  echo Updating %DEST% ...
  git -C "%DEST%" pull --ff-only
  if errorlevel 1 goto fail
) else (
  git clone "%REPO%" "%DEST%"
  if errorlevel 1 goto fail
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\tools\transfer\install_github.ps1" -Repo "%DEST%"
echo.
pause
exit /b 0
:fail
echo.
echo The install stopped, see the message above.
pause
exit /b 1
