# Asentaa siirtokansion Chimeran ja muuntimen tälle koneelle. Ajetaan siirtokansion ASENNA.bat:lla.
#
#  1. kopioi Chimeran kansioon (oletus %USERPROFILE%\chimera-vocal-synth)
#  2. asentaa puuttuvat ohjelmat wingetillä: Python 3.12 ja Bun (Rust vain -Dev-valinnalla)
#  3. siirtää mallit (jos mukana) paikoilleen, jotta niitä ei ladata uudestaan
#  4. tekee muuntimen Python-ympäristön (torch CUDA:lla jos koneessa on NVIDIA, muuten CPU)
#  5. asentaa Chimeran JavaScript-paketit (bun install)
#  6. tekee työpöydälle pikakuvakkeet ja tarkistaa asennuksen
# Loki: <kohde>\asennus.log
param([string]$Target = "", [switch]$Dev)
$ErrorActionPreference = "Continue"
$here = $PSScriptRoot

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\.bun\bin;$env:USERPROFILE\.cargo\bin"
}
function Have([string]$cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Winget([string]$id, [string[]]$extra = @()) {
  if (-not (Have "winget")) { Write-Host "   winget puuttuu: asenna $id käsin" -ForegroundColor Yellow; return }
  & winget install -e --id $id --accept-package-agreements --accept-source-agreements @extra
}
function Copy-Tree([string]$from, [string]$to) {
  if (-not (Test-Path $from)) { return }
  & robocopy $from $to /E /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { Write-Host "   kopiointi epäonnistui: $from" -ForegroundColor Red }
}
function Have-Python312 {
  if (Have "py") { & py -3.12 -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { return $true } }
  return (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe") -or (Test-Path "$env:ProgramFiles\Python312\python.exe")
}

Write-Host ""
Write-Host "CHIMERA - asennus tälle koneelle" -ForegroundColor Cyan
if (-not $Target) {
  $def = Join-Path $env:USERPROFILE "chimera-vocal-synth"
  $t = Read-Host "Asennuskansio [$def]"
  $Target = if ([string]::IsNullOrWhiteSpace($t)) { $def } else { $t.Trim() }
}
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$log = Join-Path $Target "asennus.log"
Start-Transcript -Path $log -Append | Out-Null

Write-Host "1/6 Kopioidaan Chimera kansioon $Target ..."
Copy-Tree (Join-Path $here "chimera-vocal-synth") $Target
# muunnin löytää Chimeran tästä, vaikka kansio olisi muualla kuin oletuspaikassa
[Environment]::SetEnvironmentVariable("CHIMERA_REPO", $Target, "User")
$env:CHIMERA_REPO = $Target

Write-Host "2/6 Tarvittavat ohjelmat ..."
Refresh-Path
if (-not (Have-Python312)) {
  Write-Host "   asennetaan Python 3.12"
  Winget "Python.Python.3.12" @("--scope", "user")
  Refresh-Path
} else { Write-Host "   Python 3.12 löytyi" }
if (-not (Have "bun")) {
  Write-Host "   asennetaan Bun"
  Winget "Oven-sh.Bun"
  Refresh-Path
  if (-not (Have "bun")) { powershell -NoProfile -ExecutionPolicy Bypass -c "irm bun.sh/install.ps1 | iex"; Refresh-Path }
} else { Write-Host "   Bun löytyi" }
if ($Dev) {
  if (-not (Have "cargo")) {
    Write-Host "   asennetaan Rust (moottorin kääntämiseen) ja Visual Studion C++-työkalut"
    Winget "Microsoft.VisualStudio.2022.BuildTools" @("--override", "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")
    Winget "Rustlang.Rustup"
    Refresh-Path
  }
  if (Have "rustup") { & rustup target add wasm32-unknown-unknown }
}

Write-Host "3/6 Mallit ..."
if (Test-Path (Join-Path $here "mallit")) {
  $hfHome = if ($env:HF_HOME) { $env:HF_HOME } else { Join-Path $env:USERPROFILE ".cache\huggingface" }
  Copy-Tree (Join-Path $here "mallit\huggingface") $hfHome
  Copy-Tree (Join-Path $here "mallit\torch") (Join-Path $env:USERPROFILE ".cache\torch")
  Write-Host "   siirretty"
} else { Write-Host "   ei mukana: ne ladataan ensimmäisellä muunnoksella (noin 1,3 Gt)" }

Write-Host "4/6 Muuntimen Python-ympäristö (torch lataa noin 2,5 Gt, kestää hetken) ..."
$conv = Join-Path $Target "tools\chimera-convert"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $conv "scripts\install.ps1")

Write-Host "5/6 Chimeran JavaScript-paketit ..."
Push-Location $Target
if (Have "bun") { & bun install } else { Write-Host "   Bun puuttuu: asenna se ja aja 'bun install' kansiossa $Target" -ForegroundColor Red }
Pop-Location

Write-Host "6/6 Pikakuvakkeet ja tarkistus ..."
$desk = [Environment]::GetFolderPath("Desktop")
$sh = New-Object -ComObject WScript.Shell
foreach ($l in @(@("Chimera", (Join-Path $Target "start_chimera.bat")), @("Chimera-muunnin", (Join-Path $conv "scripts\start_app.bat")))) {
  $lnk = $sh.CreateShortcut((Join-Path $desk ($l[0] + ".lnk")))
  $lnk.TargetPath = $l[1]
  $lnk.WorkingDirectory = Split-Path -Parent $l[1]
  $lnk.Save()
}
$ok = $true
function Check([string]$what, [bool]$good, [string]$fix) {
  if ($good) { Write-Host "   OK   $what" -ForegroundColor Green }
  else { Write-Host "   PUUTTUU  $what - $fix" -ForegroundColor Red; $script:ok = $false }
}
Check "chimera.wasm (Chimeran moottori)" (Test-Path (Join-Path $Target "src\wasm\chimera.wasm")) "asenna Rust: aja ASENNA.bat uudelleen valinnalla -Dev"
Check "chimera.exe (laulattaminen muuntimessa)" (Test-Path (Join-Path $Target "target\release\chimera.exe")) "aja build_chimera_cli.bat (vaatii Rustin)"
Check "Bun" (Have "bun") "winget install -e --id Oven-sh.Bun"
Check "Chimeran paketit" (Test-Path (Join-Path $Target "node_modules\vite")) "aja 'bun install' kansiossa $Target"
Check "muuntimen Python" (Test-Path (Join-Path $conv ".venv\Scripts\python.exe")) "katso $conv\out\install.log"
Check "muuntimen sovellus" (Test-Path (Join-Path $conv "app\dist\index.html")) "siirtokansio on vajaa"
$gpu = $false
if (Have "nvidia-smi") { & nvidia-smi -L 2>$null | Out-Null; $gpu = ($LASTEXITCODE -eq 0) }
Write-Host ("   GPU: " + $(if ($gpu) { "NVIDIA löytyi (muunnos nopea)" } else { "ei NVIDIA-näytönohjainta: muunnos toimii, mutta hitaammin" }))
Stop-Transcript | Out-Null
Write-Host ""
if ($ok) { Write-Host "Valmis. Työpöydällä: Chimera ja Chimera-muunnin." -ForegroundColor Green }
else { Write-Host "Asennus jäi vajaaksi, katso yllä. Loki: $log" -ForegroundColor Yellow }
