# Round trip with the real models: Chimera sings its demo songs, the converter reads them back.
# Log: tools\chimera-convert\out\smoke.log
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent (Split-Path -Parent $root)
$out = Join-Path $root "out\smoke"
New-Item -ItemType Directory -Force -Path $out | Out-Null
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
& {
  "===== render demo songs ====="
  Push-Location $repo
  & .\target\release\chimera.exe render song $out female
  Pop-Location
  Get-ChildItem $out -Filter *.wav | ForEach-Object { $_.Name }
  "Jaakko kulta, Jaakko kulta, herää jo, herää jo! Kellojasi soita, kellojasi soita: pim pom pum, pim pom pum." | Out-File -Encoding utf8 (Join-Path $out "jaakko.txt")
  "Twinkle twinkle little star, how I wonder what you are." | Out-File -Encoding utf8 (Join-Path $out "twinkle.txt")
  $jaakko = Get-ChildItem $out -Filter "jaakko*female.wav" | Select-Object -First 1
  $twinkle = Get-ChildItem $out -Filter "twinkle*female.wav" | Select-Object -First 1
  "===== convert fi: $($jaakko.Name) ====="
  & $py -m chimera_convert $jaakko.FullName (Join-Path $out "jaakko.txt") --lang fi --plot -o (Join-Path $out "jaakko.json")
  "===== convert en: $($twinkle.Name) ====="
  & $py -m chimera_convert $twinkle.FullName (Join-Path $out "twinkle.txt") --lang en --plot -o (Join-Path $out "twinkle.json")
  "===== render the conversion back ====="
  Push-Location $repo
  & .\target\release\chimera.exe render notes (Join-Path $out "twinkle.json") (Join-Path $out "twinkle-roundtrip") female
  & .\target\release\chimera.exe render notes (Join-Path $out "jaakko.json") (Join-Path $out "jaakko-roundtrip") female
  Pop-Location
  "===== SMOKE DONE ====="
} *>&1 | Out-File -FilePath (Join-Path $root "out\smoke.log") -Encoding utf8
