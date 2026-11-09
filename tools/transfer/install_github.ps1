# Asentaa GitHubista haetun Chimeran (suomen tuki) ja muuntimen käyttökuntoon. Ajetaan
# asenna_githubista.bat:lla, joka ensin hakee (tai päivittää) repon.
#
#  1. tarvittavat ohjelmat wingetillä: Python 3.12, Bun, Rust ja Visual Studion C++-työkalut
#     (moottori käännetään lähdekoodista, joten Rust tarvitaan)
#  2. Chimeran JavaScript-paketit ja moottori (chimera.wasm) sekä komentoriviohjelma (chimera.exe)
#  3. muuntimen sovellus ja Python-ympäristö (torch CUDA:lla, jos koneessa on NVIDIA)
#  4. työpöydän pikakuvakkeet ja tarkistus
# Ajetaan uudelleen päivitykseen: jo asennetut osat ohitetaan, käännökset tehdään uudestaan.
# Loki: <repo>\asennus.log
param([string]$Repo = "")
$ErrorActionPreference = "Continue"
if (-not $Repo) { $Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$conv = Join-Path $Repo "tools\chimera-convert"

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\.bun\bin;$env:USERPROFILE\.cargo\bin"
}
function Have([string]$cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Winget([string]$id, [string[]]$extra = @()) {
  if (-not (Have "winget")) { Write-Host "   winget puuttuu: asenna $id käsin" -ForegroundColor Yellow; return }
  & winget install -e --id $id --accept-package-agreements --accept-source-agreements @extra
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

Start-Transcript -Path (Join-Path $Repo "asennus.log") -Append | Out-Null
Write-Host "CHIMERA + muunnin: asennus kansioon $Repo" -ForegroundColor Cyan
[Environment]::SetEnvironmentVariable("CHIMERA_REPO", $Repo, "User")
$env:CHIMERA_REPO = $Repo

Step "1/5 Tarvittavat ohjelmat"
Refresh-Path
if (-not (Have-Python312)) { Write-Host "   asennetaan Python 3.12"; Winget "Python.Python.3.12" @("--scope", "user"); Refresh-Path } else { Write-Host "   Python 3.12 löytyi" }
if (-not (Have "bun")) {
  Write-Host "   asennetaan Bun"; Winget "Oven-sh.Bun"; Refresh-Path
  if (-not (Have "bun")) { powershell -NoProfile -ExecutionPolicy Bypass -c "irm bun.sh/install.ps1 | iex"; Refresh-Path }
} else { Write-Host "   Bun löytyi" }
if (-not (Have-Msvc)) {
  Write-Host "   asennetaan Visual Studion C++-työkalut (Rust tarvitsee niiden linkkerin; noin 3 Gt, Windows kysyy lupaa)"
  Winget "Microsoft.VisualStudio.2022.BuildTools" @("--override", "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")
} else { Write-Host "   C++-työkalut löytyivät" }
if (-not (Have "rustup")) { Write-Host "   asennetaan Rust"; Winget "Rustlang.Rustup"; Refresh-Path } else { Write-Host "   Rust löytyi" }
if (Have "rustup") {
  & rustup default stable 2>$null | Out-Null
  & rustup target add wasm32-unknown-unknown
}

Step "2/5 Chimera: JavaScript-paketit, moottori ja komentoriviohjelma (ensimmäinen käännös kestää useita minuutteja)"
Push-Location $Repo
if (Have "bun") { & bun install } else { Write-Host "   Bun puuttuu" -ForegroundColor Red }
if ((Have "cargo") -and (Have "bun")) {
  & bun run wasm
  & cargo build --release -p chimera-cli
} else { Write-Host "   Rust puuttuu: moottoria ei voitu kääntää" -ForegroundColor Red }
Pop-Location

Step "3/5 Muuntimen sovellus"
Push-Location (Join-Path $conv "app")
if (Have "bun") { & bun install; & bun run build }
Pop-Location

Step "4/5 Muuntimen Python-ympäristö (torch lataa noin 2,5 Gt)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $conv "scripts\install.ps1")

Step "5/5 Pikakuvakkeet ja tarkistus"
$desk = [Environment]::GetFolderPath("Desktop")
$sh = New-Object -ComObject WScript.Shell
foreach ($l in @(@("Chimera", (Join-Path $Repo "start_chimera.bat")), @("Chimera-muunnin", (Join-Path $conv "scripts\start_app.bat")))) {
  $lnk = $sh.CreateShortcut((Join-Path $desk ($l[0] + ".lnk")))
  $lnk.TargetPath = $l[1]
  $lnk.WorkingDirectory = Split-Path -Parent $l[1]
  $lnk.Save()
}
$ok = $true
function Check([string]$what, [bool]$good, [string]$fix) {
  if ($good) { Write-Host "   OK       $what" -ForegroundColor Green }
  else { Write-Host "   PUUTTUU  $what - $fix" -ForegroundColor Red; $script:ok = $false }
}
Check "Chimeran moottori (src\wasm\chimera.wasm)" (Test-Path (Join-Path $Repo "src\wasm\chimera.wasm")) "Rustin tai C++-työkalujen asennus jäi kesken: käynnistä kone uudelleen ja aja asennus uudestaan"
Check "chimera.exe (laulattaminen muuntimessa)" (Test-Path (Join-Path $Repo "target\release\chimera.exe")) "sama kuin yllä"
Check "Chimeran paketit" (Test-Path (Join-Path $Repo "node_modules\vite")) "aja 'bun install' kansiossa $Repo"
Check "muuntimen sovellus" (Test-Path (Join-Path $conv "app\dist\index.html")) "aja 'bun install' ja 'bun run build' kansiossa $conv\app"
Check "muuntimen Python" (Test-Path (Join-Path $conv ".venv\Scripts\python.exe")) "katso $conv\out\install.log"
$gpu = $false
if (Have "nvidia-smi") { & nvidia-smi -L 2>$null | Out-Null; $gpu = ($LASTEXITCODE -eq 0) }
Write-Host ("   GPU: " + $(if ($gpu) { "NVIDIA löytyi (muunnos nopea)" } else { "ei NVIDIA-näytönohjainta: muunnos toimii, mutta hitaammin" }))
Stop-Transcript | Out-Null
Write-Host ""
if ($ok) { Write-Host "Valmis. Työpöydällä: Chimera ja Chimera-muunnin." -ForegroundColor Green }
else { Write-Host "Asennus jäi vajaaksi, katso yllä. Loki: $Repo\asennus.log" -ForegroundColor Yellow }
