CHIMERA + Finnish support + converter: moving to another machine
================================================================

This folder holds everything the other machine needs:
  chimera-vocal-synth\   Chimera with all its changes (git history and local commits included),
                         the built engine (src\wasm\chimera.wasm) and chimera.exe, and the
                         converter (tools\chimera-convert) with its app already built
  models\                (if included) the lyrics aligner and the voice separation model
  INSTALL.bat            installs everything

INSTALL
  1. Copy the whole ChimeraTransfer folder to the new machine (or run it from the USB stick).
  2. Double-click INSTALL.bat. It asks for an install folder (Enter = %USERPROFILE%\chimera-vocal-synth).
  3. The installer fetches the missing tools (Python 3.12, Bun) with winget and the Python
     packages (torch, about 2.5 GB). This usually takes 10-20 minutes.
  4. Two shortcuts appear on the desktop: "Chimera" and "Chimera Converter".

REQUIREMENTS
  - Windows 10/11 and an internet connection during the install.
  - An NVIDIA GPU makes converting much faster; without one the converter runs on the CPU.
  - Rust is NOT needed to use Chimera. To change and build the engine on the new machine, run
    in a command prompt:  INSTALL.bat -Dev
    (also installs Rust and the Visual Studio C++ build tools, about 3 GB).

NOTES
  - The Python environment and node_modules can't be copied between machines, so they are
    installed again.
  - Your songs (out\sessions, public\shows) contain copyrighted material: for your own use
    only, not for git or sharing.
  - Logs: <install folder>\install.log and tools\chimera-convert\out\install.log
