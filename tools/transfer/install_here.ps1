# Installs a transfer folder's Chimera and converter on this machine. Run by the transfer folder's
# INSTALL.bat.
#
#  1. copies Chimera to a folder (default %USERPROFILE%\chimera-vocal-synth)
#  2. installs what is missing with winget: Python 3.12 and Bun (Rust only with -Dev)
#  3. puts the models (when included) in place, so they aren't downloaded again
#  4. makes the converter's Python environment (torch with CUDA on an NVIDIA GPU, else the CPU build)
#  5. installs Chimera's JavaScript packages (bun install)
#  6. makes desktop shortcuts and checks the install
# Log: <destination>\install.log
param([string]$Target = "", [switch]$Dev)
$ErrorActionPreference = "Continue"
$here = $PSScriptRoot

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\.bun\bin;$env:USERPROFILE\.cargo\bin"
}
function Have([string]$cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
# not named "winget": PowerShell function names ignore case, so a function Winget calling winget
# called itself until the call depth overflowed
function Install-WithWinget([string]$id, [string[]]$extra = @()) {
  $wg = Get-Command winget.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $wg) { Write-Host "   winget is missing: install $id by hand" -ForegroundColor Yellow; return }
  & $wg.Source install -e --id $id --accept-package-agreements --accept-source-agreements @extra
}
function Have-Python312 {
  if (Have "py") { & py -3.12 -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { return $true } }
  return (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe") -or (Test-Path "$env:ProgramFiles\Python312\python.exe")
}
function Copy-Tree([string]$from, [string]$to) {
  if (-not (Test-Path $from)) { return }
  & robocopy $from $to /E /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { Write-Host "   copy failed: $from" -ForegroundColor Red }
}

Write-Host ""
Write-Host "CHIMERA - install on this machine" -ForegroundColor Cyan
if (-not $Target) {
  $def = Join-Path $env:USERPROFILE "chimera-vocal-synth"
  $t = Read-Host "Install folder [$def]"
  $Target = if ([string]::IsNullOrWhiteSpace($t)) { $def } else { $t.Trim() }
}
$Repo = $Target
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$log = Join-Path $Target "install.log"
Start-Transcript -Path $log -Append | Out-Null

Write-Host "1/6 Copying Chimera to $Target ..."
Copy-Tree (Join-Path $here "chimera-vocal-synth") $Target
# the converter finds Chimera here, wherever the folder is
[Environment]::SetEnvironmentVariable("CHIMERA_REPO", $Target, "User")
$env:CHIMERA_REPO = $Target

Write-Host "2/6 Tools ..."
Refresh-Path
if (-not (Have-Python312)) {
  Write-Host "   installing Python 3.12"
  Install-WithWinget "Python.Python.3.12" @("--scope", "user")
  Refresh-Path
} else { Write-Host "   Python 3.12 found" }
if (-not (Have "bun")) {
  Write-Host "   installing Bun"
  Install-WithWinget "Oven-sh.Bun"
  Refresh-Path
  if (-not (Have "bun")) { powershell -NoProfile -ExecutionPolicy Bypass -c "irm bun.sh/install.ps1 | iex"; Refresh-Path }
} else { Write-Host "   Bun found" }
if ($Dev) {
  if (-not (Have "cargo")) {
    Write-Host "   installing Rust (to build the engine) and the Visual Studio C++ build tools"
    Install-WithWinget "Microsoft.VisualStudio.2022.BuildTools" @("--override", "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")
    Install-WithWinget "Rustlang.Rustup"
    Refresh-Path
  }
  if (Have "rustup") { & rustup target add wasm32-unknown-unknown }
}

Write-Host "3/6 Models ..."
if (Test-Path (Join-Path $here "models")) {
  $hfHome = if ($env:HF_HOME) { $env:HF_HOME } else { Join-Path $env:USERPROFILE ".cache\huggingface" }
  Copy-Tree (Join-Path $here "models\huggingface") $hfHome
  Copy-Tree (Join-Path $here "models\torch") (Join-Path $env:USERPROFILE ".cache\torch")
  Write-Host "   moved"
} else { Write-Host "   not included: they are downloaded on the first conversion (about 1.3 GB)" }

Write-Host "4/6 Converter Python environment (torch downloads about 2.5 GB, this takes a while) ..."
$conv = Join-Path $Target "tools\chimera-convert"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $conv "scripts\install.ps1")

Write-Host "5/6 Chimera JavaScript packages ..."
Push-Location $Target
if (Have "bun") { & bun install } else { Write-Host "   Bun is missing: install it and run 'bun install' in $Target" -ForegroundColor Red }
Pop-Location

Write-Host "6/6 Shortcuts and check ..."
$desk = [Environment]::GetFolderPath("Desktop")
$sh = New-Object -ComObject WScript.Shell
foreach ($l in @(@("Chimera", (Join-Path $Repo "start_chimera.bat")), @("Chimera Converter", (Join-Path $conv "scripts\start_app.bat")))) {
  $lnk = $sh.CreateShortcut((Join-Path $desk ($l[0] + ".lnk")))
  $lnk.TargetPath = $l[1]
  $lnk.WorkingDirectory = Split-Path -Parent $l[1]
  $lnk.Save()
}
$ok = $true
function Check([string]$what, [bool]$good, [string]$fix) {
  if ($good) { Write-Host "   OK       $what" -ForegroundColor Green }
  else { Write-Host "   MISSING  $what - $fix" -ForegroundColor Red; $script:ok = $false }
}
Check "chimera.wasm (Chimera's engine)" (Test-Path (Join-Path $Target "src\wasm\chimera.wasm")) "install Rust: run INSTALL.bat -Dev"
Check "chimera.exe (Sing with Chimera in the converter)" (Test-Path (Join-Path $Target "target\release\chimera.exe")) "run build_chimera_cli.bat (needs Rust)"
Check "Bun" (Have "bun") "winget install -e --id Oven-sh.Bun"
Check "Chimera packages" (Test-Path (Join-Path $Target "node_modules\vite")) "run 'bun install' in $Target"
Check "converter Python" (Test-Path (Join-Path $conv ".venv\Scripts\python.exe")) "see $conv\out\install.log"
Check "converter app" (Test-Path (Join-Path $conv "app\dist\index.html")) "the transfer folder is incomplete"
$gpu = $false
if (Have "nvidia-smi") { & nvidia-smi -L 2>$null | Out-Null; $gpu = ($LASTEXITCODE -eq 0) }
Write-Host ("   GPU: " + $(if ($gpu) { "NVIDIA found (fast conversion)" } else { "no NVIDIA GPU: the converter works, but slower" }))
Stop-Transcript | Out-Null
Write-Host ""
if ($ok) { Write-Host "Done. On the desktop: Chimera and Chimera Converter." -ForegroundColor Green }
else { Write-Host "The install is incomplete, see above. Log: $log" -ForegroundColor Yellow }
