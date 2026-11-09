# Environment check for chimera-convert. Writes tools\chimera-convert\out\env-check.txt
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "out\env-check.txt"
New-Item -ItemType Directory -Force -Path (Join-Path $root "out") | Out-Null
function Section($t) { "`n===== $t =====" }
& {
  Section "OS"
  [System.Environment]::OSVersion.VersionString
  (Get-CimInstance Win32_OperatingSystem).Caption
  Section "CPU / RAM"
  (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
  "{0:N1} GB RAM" -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
  Section "GPU"
  Get-CimInstance Win32_VideoController | ForEach-Object { "$($_.Name)  driver $($_.DriverVersion)" }
  Section "nvidia-smi"
  try { nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv 2>&1; nvidia-smi 2>&1 | Select-String "CUDA Version" } catch { "nvidia-smi not found" }
  Section "Disk"
  Get-PSDrive -PSProvider FileSystem | ForEach-Object { "{0}: free {1:N1} GB of {2:N1} GB" -f $_.Name, ($_.Free/1GB), (($_.Used+$_.Free)/1GB) }
  Section "Python launcher (py -0p)"
  try { py -0p 2>&1 } catch { "py launcher not found" }
  Section "python on PATH"
  try { (Get-Command python -All -ErrorAction Stop) | ForEach-Object { $_.Source }; python --version 2>&1 } catch { "python not on PATH" }
  Section "Tools"
  foreach ($c in "ffmpeg","cargo","rustc","bun","git","node") {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { "$c : $($cmd.Source)"; try { (& $c --version 2>&1 | Select-Object -First 1) } catch {} } else { "$c : not found" }
  }
  Section "chimera.exe"
  $exe = Join-Path (Split-Path -Parent (Split-Path -Parent $root)) "target\release\chimera.exe"
  if (Test-Path $exe) { "found: $exe"; & $exe help 2>&1 | Select-Object -First 3 } else { "not found: $exe" }
  Section "Existing venv"
  $venvPy = Join-Path $root ".venv\Scripts\python.exe"
  if (Test-Path $venvPy) { & $venvPy -c "import sys; print(sys.version)"; & $venvPy -m pip list 2>&1 | Select-String "torch|demucs|transformers|librosa|crepe" } else { "no .venv yet" }
  Section "Global python packages (torch?)"
  try { py -3.11 -c "import torch,sys; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" 2>&1 } catch { "py -3.11 failed" }
  Section "Hugging Face / torch caches"
  foreach ($p in "$env:USERPROFILE\.cache\huggingface", "$env:USERPROFILE\.cache\torch") {
    if (Test-Path $p) { "{0}: {1:N2} GB" -f $p, ((Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum/1GB) } else { "${p}: none" }
  }
  Section "Done"
  Get-Date
} *>&1 | Out-File -FilePath $log -Encoding utf8
