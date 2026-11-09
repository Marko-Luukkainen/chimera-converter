# Starts (or restarts) the converter app: http://127.0.0.1:5320, opened in the browser. Close the window to stop.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Install first: scripts\install.bat"; Read-Host "Press Enter"; exit 1 }
if (-not (Test-Path "app\dist\index.html")) { Write-Host "app\dist is missing: run bun install and bun run build in the app folder"; Read-Host "Press Enter"; exit 1 }
# a server from an earlier start still holding the port is stopped, so this always (re)starts
Get-NetTCPConnection -LocalPort 5320 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Stopping the earlier server (pid $($_.OwningProcess))"
  Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
& $py -m chimera_convert.server
