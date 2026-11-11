# Installs chimera-convert's Python packages into tools\chimera-convert\.venv: torch with CUDA when
# an NVIDIA GPU is found (else the CPU build), then requirements.txt, then the RoFormer separator
# (install_separator.ps1, which keeps that torch), then checks and tests.
# Log: tools\chimera-convert\out\install.log
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "out\install.log"
New-Item -ItemType Directory -Force -Path (Join-Path $root "out") | Out-Null
Set-Location $root

function Find-Python312 {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $p) { return "$p".Trim() }
  }
  foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:ProgramFiles\Python312\python.exe")) {
    if (Test-Path $c) { return $c }
  }
  return $null
}

& {
  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $base = Find-Python312
    if (-not $base) { "Python 3.12 not found: install it (winget install -e --id Python.Python.3.12) and run this again"; return }
    "creating .venv with $base"
    & $base -m venv .venv
  }
  $py = Join-Path $root ".venv\Scripts\python.exe"
  & $py -m pip install --upgrade pip
  $gpu = $false
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { & nvidia-smi -L 2>$null | Out-Null; $gpu = ($LASTEXITCODE -eq 0) }
  if ($gpu) {
    "===== torch (CUDA 12.8, NVIDIA GPU found) ====="
    & $py -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
  } else {
    "===== torch (CPU: no NVIDIA GPU found; converting is slower) ====="
    & $py -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
  }
  "===== requirements ====="
  & $py -m pip install -r requirements.txt
  "===== RoFormer separator (optional: Demucs works without it) ====="
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_separator.ps1")
  "===== check ====="
  & $py -c "import torch, torchaudio, librosa, torchcrepe, demucs, transformers; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-'); print('torchaudio', torchaudio.__version__, 'transformers', transformers.__version__, 'librosa', librosa.__version__)"
  "===== tests ====="
  & $py -m pytest -q
  "===== INSTALL DONE ====="
} *>&1 | Tee-Object -FilePath $log
