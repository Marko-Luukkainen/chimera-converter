# Installs the RoFormer separator (--separator roformer, Lead voice only) into the converter's .venv
# without touching its torch. Run by install.ps1; also on its own: install_separator.bat.
#
# audio-separator needs torchvision. From PyPI, pip takes the newest torchvision and with it a torch
# from PyPI, which replaces the CUDA torch with a CPU one (seen on a real install: torch 2.11.0+cu128
# would have become 2.15.0). So torchvision comes from PyTorch's own index, the build that goes with
# the torch already installed (torch 2.N -> torchvision 0.N+15), and pip first only says what it
# would do: if that still changes torch, torchaudio, numpy or demucs, nothing is installed.
# Log: tools\chimera-convert\out\install_separator.log
# -Force: check and install again even when it is there. -Python: another environment's python.exe.
param([switch]$Force, [string]$Python = "")
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$py = if ($Python) { $Python } else { Join-Path $root ".venv\Scripts\python.exe" }
$log = Join-Path $root "out\install_separator.log"
New-Item -ItemType Directory -Force -Path (Join-Path $root "out") | Out-Null
Set-Location $root

& {
  if (-not (Test-Path $py)) { "The converter's Python is missing: run install.bat first"; return }
  $have = & $py -c "import importlib.util as u; print(int(bool(u.find_spec('audio_separator') and u.find_spec('audioread'))))" 2>$null
  if ("$have".Trim() -eq "1" -and -not $Force) { "RoFormer separator already installed"; return }

  # the torch that is here: version and build (cu128, cpu, ...)
  $tv = & $py -c "import torch; v, _, b = torch.__version__.partition('+'); b = b or 'cpu'; m = int(v.split('.')[1]); print('torchvision==0.%d.*' % (m + 15), b, int(torch.cuda.is_available()))" 2>$null
  if (-not $tv) { "torch is missing: run install.bat first"; return }
  $spec, $build, $cuda = "$tv".Trim() -split " "
  $extra = if ($cuda -eq "1") { "audio-separator[gpu]>=0.48" } else { "audio-separator[cpu]>=0.48" }
  $index = "https://download.pytorch.org/whl/$build"
  "torch build $build, so $spec from $index and $extra"

  $want = @($spec, $extra, "audioread")
  $dry = & $py -m pip install --dry-run @want --extra-index-url $index 2>&1 | Out-String
  $would = ($dry -split "`n" | Where-Object { $_ -match "^Would install" }) -join " "
  $touch = [regex]::Matches($would, "(?i)(?<=\s)(torch|torchaudio|numpy|demucs)-\d\S*") | ForEach-Object { $_.Value }
  if (-not $would -and $LASTEXITCODE -ne 0) {
    "RoFormer separator NOT installed: pip could not resolve it"
    $dry
    return
  }
  if ($touch) {
    "RoFormer separator NOT installed: it would change $($touch -join ', '). Demucs still works."
    $dry
    return
  }
  & $py -m pip install @want --extra-index-url $index
  & $py -c "import torch, numpy; from audio_separator.separator import Separator; print('RoFormer separator OK: torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'numpy', numpy.__version__)"
} *>&1 | Tee-Object -FilePath $log
