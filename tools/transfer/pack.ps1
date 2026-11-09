# Kokoaa Chimeran (suomen tuki mukana) ja muuntimen siirtokansioksi toiselle koneelle.
# Ajetaan VANHALLA koneella: siirra_toiselle_koneelle.bat. Uudella koneella ajetaan siirtokansion ASENNA.bat.
#
# Mukaan tulee repo kaikkine paikallisine muutoksineen ja committeineen (.git), valmiiksi kaannetyt
# chimera.wasm ja chimera.exe (uusi kone ei tarvitse Rustia), muuntimen sovellus valmiiksi kaannettyna,
# ja halutessa mallit (noin 1,3 Gt, saastaa latauksen) seka omat kappaleet (out\sessions, public\shows).
# Python-ymparisto (.venv) ja node_modules tehdaan uudella koneella uudestaan: niita ei voi siirtaa.
param([string]$Dest = "", [switch]$NoSongs, [switch]$NoModels)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # tools\transfer -> repo

function Ask([string]$q, [bool]$def = $true) {
  $d = if ($def) { "K/e" } else { "k/E" }
  $a = Read-Host "$q [$d]"
  if ([string]::IsNullOrWhiteSpace($a)) { return $def }
  $a = $a.Trim().ToLower()
  return ($a.StartsWith("k") -or $a.StartsWith("y"))
}

function Copy-Tree([string]$from, [string]$to, [string[]]$exclude = @()) {
  if (-not (Test-Path $from)) { return }
  $ra = @($from, $to, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH", "/NJS")
  if ($exclude.Count) { $ra += "/XD"; $ra += $exclude }
  & robocopy @ra | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "kopiointi epaonnistui: $from (robocopy $LASTEXITCODE)" }
}

Write-Host ""
Write-Host "CHIMERA - siirto toiselle koneelle" -ForegroundColor Cyan
Write-Host "Repo: $repo"
if (-not $Dest) {
  Write-Host "Mihin siirtokansio tehdaan? Esim. USB-tikku (E:\), verkkojako (\\TOINENKONE\jako) tai kansio (C:\Siirto)."
  $Dest = Read-Host "Kohde"
}
if (-not $Dest) { throw "kohde puuttuu" }
$out = Join-Path $Dest "ChimeraSiirto"
$songs = if ($NoSongs) { $false } else { Ask "Otetaanko omat kappaleet mukaan (muunnokset, show't; tekijanoikeudellista materiaalia, vain omaan kayttoon)?" }
$models = if ($NoModels) { $false } else { Ask "Otetaanko mallit mukaan (noin 1,3 Gt; muuten uusi kone lataa ne itse ensimmaisella kerralla)?" }

$hf = Join-Path $env:USERPROFILE ".cache\huggingface\hub\models--MahmoudAshraf--mms-300m-1130-forced-aligner"
if ($env:HF_HOME) { $hf = Join-Path $env:HF_HOME "hub\models--MahmoudAshraf--mms-300m-1130-forced-aligner" }
$th = Join-Path $env:USERPROFILE ".cache\torch\hub\checkpoints"

New-Item -ItemType Directory -Force -Path $out | Out-Null
$dst = Join-Path $out "chimera-vocal-synth"
Write-Host "1/5 Repo (koodi, git-historia, paikalliset muutokset) ..."
$conv = Join-Path $repo "tools\chimera-convert"
Copy-Tree $repo $dst @(
  (Join-Path $repo "node_modules"), (Join-Path $repo "target"), (Join-Path $repo "out"), (Join-Path $repo "dist"),
  (Join-Path $repo "public\shows"),
  (Join-Path $conv ".venv"), (Join-Path $conv ".pytest_cache"), (Join-Path $conv "out"), (Join-Path $conv "app\node_modules")
)
# pycache-kansiot pois (Pythonin valimuistia)
Get-ChildItem -Path $dst -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "2/5 Valmiiksi kaannetyt ohjelmat (chimera.exe, chimera.wasm) ..."
$exe = Join-Path $repo "target\release\chimera.exe"
if (Test-Path $exe) {
  New-Item -ItemType Directory -Force -Path (Join-Path $dst "target\release") | Out-Null
  Copy-Item $exe (Join-Path $dst "target\release\chimera.exe") -Force
} else { Write-Host "   chimera.exe puuttuu (aja build_chimera_cli.bat): uusi kone tarvitsee silloin Rustin" -ForegroundColor Yellow }
if (-not (Test-Path (Join-Path $dst "src\wasm\chimera.wasm"))) { Write-Host "   chimera.wasm puuttuu: uusi kone tarvitsee Rustin" -ForegroundColor Yellow }

Write-Host "3/5 Omat kappaleet ..."
if ($songs) {
  Copy-Tree (Join-Path $conv "out\sessions") (Join-Path $dst "tools\chimera-convert\out\sessions")
  Copy-Tree (Join-Path $repo "public\shows") (Join-Path $dst "public\shows")
} else { Write-Host "   ohitettu" }

Write-Host "4/5 Mallit ..."
if ($models) {
  if (Test-Path $hf) { Copy-Tree $hf (Join-Path $out "mallit\huggingface\hub\models--MahmoudAshraf--mms-300m-1130-forced-aligner") }
  else { Write-Host "   kohdistusmallia ei loytynyt ($hf)" }
  if (Test-Path $th) { Copy-Tree $th (Join-Path $out "mallit\torch\hub\checkpoints") }
} else { Write-Host "   ohitettu" }

Write-Host "5/5 Asennusohjelma ..."
Copy-Item (Join-Path $PSScriptRoot "install_here.ps1") (Join-Path $out "install_here.ps1") -Force
Copy-Item (Join-Path $PSScriptRoot "ASENNA.bat") (Join-Path $out "ASENNA.bat") -Force
Copy-Item (Join-Path $PSScriptRoot "LUE_MINUT.txt") (Join-Path $out "LUE_MINUT.txt") -Force

$size = (Get-ChildItem $out -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1GB
Write-Host ""
Write-Host ("Valmis: {0} ({1:N2} Gt)" -f $out, $size) -ForegroundColor Green
Write-Host "Uudella koneella: avaa kansio ChimeraSiirto ja kaksoisnapsauta ASENNA.bat."
