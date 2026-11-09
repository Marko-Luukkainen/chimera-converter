@echo off
setlocal
title CHIMERA + muunnin - asennus GitHubista
rem Hakee Chimeran (suomen tuki) ja muuntimen GitHubista ja asentaa ne kayttokuntoon.
rem Ajetaan uudelleen paivitykseen. Kohdekansion voi antaa: asenna_githubista.bat D:\chimera
set "REPO=https://github.com/Marko-Luukkainen/chimera-converter.git"
set "DEST=%USERPROFILE%\chimera-converter"
if not "%~1"=="" set "DEST=%~1"
echo.
echo CHIMERA + muunnin asennetaan kansioon %DEST%
echo Ensimmainen asennus lataa noin 6-8 Gt ja kestaa 20-40 minuuttia. Windows voi kysya lupaa asennuksille.
echo.
where winget >nul 2>nul
if errorlevel 1 (
  echo winget puuttuu: asenna tai paivita "App Installer" Microsoft Storesta ja aja tama uudelleen.
  goto fail
)
where git >nul 2>nul
if errorlevel 1 (
  echo Asennetaan Git ...
  winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
  set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
)
where git >nul 2>nul
if errorlevel 1 (
  echo Git ei asentunut.
  goto fail
)
if exist "%DEST%\.git" (
  echo Paivitetaan %DEST% ...
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
echo Asennus keskeytyi, katso viesti ylla.
pause
exit /b 1
