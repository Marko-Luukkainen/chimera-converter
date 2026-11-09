# Packs Chimera (with the Finnish support) and the converter into a transfer folder for another
# machine. Run on the OLD machine: transfer_to_another_pc.bat. On the new machine run the transfer
# folder's INSTALL.bat.
#
# Included: the repo with all its local changes and commits (.git), the built chimera.wasm and
# chimera.exe (the new machine needs no Rust), the converter app already built and, if you want,
# the models (about 1.3 GB, saves the download) and your songs (out\sessions, public\shows).
# The Python environment (.venv) and node_modules are made again on the new machine: they can't move.
param([string]$Dest = "", [switch]$NoSongs, [switch]$NoModels)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # tools\transfer -> repo

function Ask([string]$q, [bool]$def = $true) {
  $d = if ($def) { "Y/n" } else { "y/N" }
  $a = Read-Host "$q [$d]"
  if ([string]::IsNullOrWhiteSpace($a)) { return $def }
  $a = $a.Trim().ToLower()
  return ($a.StartsWith("y") -or $a.StartsWith("k"))
}

function Copy-Tree([string]$from, [string]$to, [string[]]$exclude = @()) {
  if (-not (Test-Path $from)) { return }
  $ra = @($from, $to, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH", "/NJS")
  if ($exclude.Count) { $ra += "/XD"; $ra += $exclude }
  & robocopy @ra | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "copy failed: $from (robocopy $LASTEXITCODE)" }
}

Write-Host ""
Write-Host "CHIMERA - transfer to another machine" -ForegroundColor Cyan
Write-Host "Repo: $repo"
if (-not $Dest) {
  Write-Host "Where should the transfer folder go? E.g. a USB stick (E:\), a network share (\\OTHERPC\share) or a folder (C:\Transfer)."
  $Dest = Read-Host "Destination"
}
if (-not $Dest) { throw "no destination" }
$out = Join-Path $Dest "ChimeraTransfer"
$songs = if ($NoSongs) { $false } else { Ask "Include your songs (conversions, shows; copyrighted material, for your own use only)?" }
$models = if ($NoModels) { $false } else { Ask "Include the models (about 1.3 GB; otherwise the new machine downloads them on first use)?" }

$hf = Join-Path $env:USERPROFILE ".cache\huggingface\hub\models--MahmoudAshraf--mms-300m-1130-forced-aligner"
if ($env:HF_HOME) { $hf = Join-Path $env:HF_HOME "hub\models--MahmoudAshraf--mms-300m-1130-forced-aligner" }
$th = Join-Path $env:USERPROFILE ".cache\torch\hub\checkpoints"

New-Item -ItemType Directory -Force -Path $out | Out-Null
$dst = Join-Path $out "chimera-vocal-synth"
Write-Host "1/5 Repo (code, git history, local changes) ..."
$conv = Join-Path $repo "tools\chimera-convert"
Copy-Tree $repo $dst @(
  (Join-Path $repo "node_modules"), (Join-Path $repo "target"), (Join-Path $repo "out"), (Join-Path $repo "dist"),
  (Join-Path $repo "public\shows"),
  (Join-Path $conv ".venv"), (Join-Path $conv ".pytest_cache"), (Join-Path $conv "out"), (Join-Path $conv "app\node_modules")
)
Get-ChildItem -Path $dst -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "2/5 Built programs (chimera.exe, chimera.wasm) ..."
$exe = Join-Path $repo "target\release\chimera.exe"
if (Test-Path $exe) {
  New-Item -ItemType Directory -Force -Path (Join-Path $dst "target\release") | Out-Null
  Copy-Item $exe (Join-Path $dst "target\release\chimera.exe") -Force
} else { Write-Host "   chimera.exe is missing (run build_chimera_cli.bat): the new machine then needs Rust" -ForegroundColor Yellow }
if (-not (Test-Path (Join-Path $dst "src\wasm\chimera.wasm"))) { Write-Host "   chimera.wasm is missing: the new machine needs Rust" -ForegroundColor Yellow }

Write-Host "3/5 Your songs ..."
if ($songs) {
  Copy-Tree (Join-Path $conv "out\sessions") (Join-Path $dst "tools\chimera-convert\out\sessions")
  Copy-Tree (Join-Path $repo "public\shows") (Join-Path $dst "public\shows")
} else { Write-Host "   skipped" }

Write-Host "4/5 Models ..."
if ($models) {
  if (Test-Path $hf) { Copy-Tree $hf (Join-Path $out "models\huggingface\hub\models--MahmoudAshraf--mms-300m-1130-forced-aligner") }
  else { Write-Host "   alignment model not found ($hf)" }
  if (Test-Path $th) { Copy-Tree $th (Join-Path $out "models\torch\hub\checkpoints") }
} else { Write-Host "   skipped" }

Write-Host "5/5 Installer ..."
Copy-Item (Join-Path $PSScriptRoot "install_here.ps1") (Join-Path $out "install_here.ps1") -Force
Copy-Item (Join-Path $PSScriptRoot "INSTALL.bat") (Join-Path $out "INSTALL.bat") -Force
Copy-Item (Join-Path $PSScriptRoot "README.txt") (Join-Path $out "README.txt") -Force

$size = (Get-ChildItem $out -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1GB
Write-Host ""
Write-Host ("Done: {0} ({1:N2} GB)" -f $out, $size) -ForegroundColor Green
Write-Host "On the new machine: open the ChimeraTransfer folder and double-click INSTALL.bat."
