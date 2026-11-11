# Installs Chimera (with Finnish support) and the converter from a GitHub checkout. Run by
# install_from_github.bat, which clones (or updates) the repo first.
#
#  1. the tools, with winget: Python 3.12, Bun, Rust and the Visual Studio C++ build tools
#     (the engine is built from source, so Rust is needed)
#  2. Chimera's JavaScript packages, the engine (chimera.wasm) and the CLI (chimera.exe)
#  3. the converter app and its Python environment (torch with CUDA on an NVIDIA GPU, and the
#     RoFormer separator built for that torch)
#  4. desktop shortcuts and a check
# Run again to update: what is installed is skipped, the builds are redone.
# Log: <repo>\install.log
param([string]$Repo = "")
$ErrorActionPreference = "Continue"
if (-not $Repo) { $Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$conv = Join-Path $Repo "tools\chimera-convert"

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
function Have-Msvc {
  $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
  if (-not (Test-Path $vswhere)) { return $false }
  $p = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
  return [bool]$p
}
function Step([string]$text) { Write-Host ""; Write-Host $text -ForegroundColor Cyan }

Start-Transcript -Path (Join-Path $Repo "install.log") -Append | Out-Null
Write-Host "CHIMERA + converter: installing in $Repo" -ForegroundColor Cyan
[Environment]::SetEnvironmentVariable("CHIMERA_REPO", $Repo, "User")
$env:CHIMERA_REPO = $Repo

Step "1/5 Tools"
Refresh-Path
if (-not (Have-Python312)) { Write-Host "   installing Python 3.12"; Install-WithWinget "Python.Python.3.12" @("--scope", "user"); Refresh-Path } else { Write-Host "   Python 3.12 found" }
if (-not (Have "bun")) {
  Write-Host "   installing Bun"; Install-WithWinget "Oven-sh.Bun"; Refresh-Path
  if (-not (Have "bun")) { powershell -NoProfile -ExecutionPolicy Bypass -c "irm bun.sh/install.ps1 | iex"; Refresh-Path }
} else { Write-Host "   Bun found" }
if (-not (Have-Msvc)) {
  Write-Host "   installing the Visual Studio C++ build tools (Rust needs their linker; about 3 GB, Windows asks for permission)"
  Install-WithWinget "Microsoft.VisualStudio.2022.BuildTools" @("--override", "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")
} else { Write-Host "   C++ build tools found" }
if (-not (Have "rustup")) { Write-Host "   installing Rust"; Install-WithWinget "Rustlang.Rustup"; Refresh-Path } else { Write-Host "   Rust found" }
if (Have "rustup") {
  & rustup default stable 2>$null | Out-Null
  & rustup target add wasm32-unknown-unknown
}

Step "2/5 Chimera: JavaScript packages, engine and CLI (the first build takes several minutes)"
Push-Location $Repo
if (Have "bun") { & bun install } else { Write-Host "   Bun is missing" -ForegroundColor Red }
if ((Have "cargo") -and (Have "bun")) {
  & bun run wasm
  & cargo build --release -p chimera-cli
} else { Write-Host "   Rust is missing: the engine could not be built" -ForegroundColor Red }
Pop-Location

Step "3/5 Converter app"
Push-Location (Join-Path $conv "app")
if (Have "bun") { & bun install; & bun run build }
Pop-Location

Step "4/5 Converter Python environment (torch downloads about 2.5 GB)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $conv "scripts\install.ps1")

Step "5/5 Shortcuts and check"
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
Check "Chimera engine (src\wasm\chimera.wasm)" (Test-Path (Join-Path $Repo "src\wasm\chimera.wasm")) "Rust or the C++ build tools didn't finish installing: restart the machine and run the installer again"
Check "chimera.exe (Sing with Chimera in the converter)" (Test-Path (Join-Path $Repo "target\release\chimera.exe")) "as above"
Check "Chimera packages" (Test-Path (Join-Path $Repo "node_modules\vite")) "run 'bun install' in $Repo"
Check "converter app" (Test-Path (Join-Path $conv "app\dist\index.html")) "run 'bun install' and 'bun run build' in $conv\app"
Check "converter Python" (Test-Path (Join-Path $conv ".venv\Scripts\python.exe")) "see $conv\out\install.log"
$cpy = Join-Path $conv ".venv\Scripts\python.exe"
if (Test-Path $cpy) {
  & $cpy -c "import audio_separator, audioread" 2>$null
  if ($LASTEXITCODE -eq 0) { Write-Host "   OK       RoFormer separator (optional)" -ForegroundColor Green }
  else { Write-Host "   SKIPPED  RoFormer separator (optional; Demucs works): see $conv\out\install_separator.log" -ForegroundColor Yellow }
}
$gpu = $false
if (Have "nvidia-smi") { & nvidia-smi -L 2>$null | Out-Null; $gpu = ($LASTEXITCODE -eq 0) }
Write-Host ("   GPU: " + $(if ($gpu) { "NVIDIA found (fast conversion)" } else { "no NVIDIA GPU: the converter works, but slower" }))
Stop-Transcript | Out-Null
Write-Host ""
if ($ok) { Write-Host "Done. On the desktop: Chimera and Chimera Converter." -ForegroundColor Green }
else { Write-Host "The install is incomplete, see above. Log: $Repo\install.log" -ForegroundColor Yellow }
