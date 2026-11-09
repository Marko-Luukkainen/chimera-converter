# chimera-converter

Converter for Chimera singer. Convert Finnish and English language

This repository is [CHIMERA](https://github.com/jamesondh/chimera-vocal-synth) by Jameson Hodge
(MIT) with additions:

- **Finnish speech and singing**: rule G2P, first-syllable stress, vowel quantity and geminates,
  Finnish vowel table, Finnish R/S/T, Finnish lyrics in Sing mode and on the duet page.
- **Converter** ([tools/chimera-convert](tools/chimera-convert/README.md)): a sung recording
  (wav/mp3) and its lyrics become a Chimera melody file: voice separation, pitch and note
  tracking, lyrics alignment, a check of what counts as singing, and a piano-roll editor app.
- **Live songs**: Sing mode plays a converted song with live voice controls; the duet page
  (`?show=<id>`) sings it live with a voice panel (character, body, vibrato, tone, grit).
- **Windows install**: `install_from_github.bat` (from this repository) and
  `transfer_to_another_pc.bat` (a working copy with its songs, to another machine).

## Install on Windows

Download [`install_from_github.bat`](install_from_github.bat) (Raw → save) and double-click it. It
installs Git, Python 3.12, Bun, Rust and the Visual Studio C++ build tools with winget where
missing, clones this repository to `%USERPROFILE%\chimera-converter`, builds the engine
(`chimera.wasm`) and the CLI (`chimera.exe`), the converter app and its Python environment (torch
with CUDA on an NVIDIA GPU, else the CPU build), and puts "Chimera" and "Chimera Converter" on the
desktop. The first run downloads 6–8 GB and takes 20–40 minutes; run it again to update.

No recordings, conversions or shows are committed (`out/`, `public/shows/`): they are often
covers of songs nobody here has the rights to.

The original README follows.

---

## CHIMERA

A physical-modeling voice synthesizer in the browser. Every sound comes from a simulated
airway (lungs, vocal folds or syrinx, a branched vocal tract, lips, nose), not from samples.
The engine is Rust, compiled to WebAssembly for an AudioWorklet; the same code runs natively
for tests and the `chimera` CLI.

## What it does

- **Play**: drag the tongue, lips and jaw in a live cutaway of the head; vowel pad, encoders,
  computer keyboard and Web MIDI.
- **Speak**: English text (CMUdict with a letter-to-sound fallback), Finnish text (spelling
  rules, first-syllable stress, long vowels and geminates) or IPA, turned into gestures and
  prosody, with the gestural score and a consonant chart on screen.
- **Sing**: piano roll with lyrics per note; consonants land before the beat.
- **Beatbox**: pads and a step sequencer, every drum an articulatory gesture.
- **Bestiary**: songbird (two-voice syrinx), seal, alligator and elephant.
- **Duet** (`?show=<id>`): two 3D heads replay a pre-rendered song.

Male, female and child bodies blend continuously. Everything on screen animates from live
engine state: pressure in the airway, airflow, the vocal folds, spectra and formants.

## Run it

Needs Rust with the `wasm32-unknown-unknown` target, and Bun.

```sh
bun install
bun run dev        # builds the wasm, then Vite on 127.0.0.1:5317
bun run test       # wasm build, cargo test --workspace, bun test tests
```

The AudioWorklet needs a secure context, so open it on localhost or over HTTPS (for example
`tailscale serve`). Vercel builds it with `vercel.json`.

Offline renders and measurement:

```sh
cargo run --release -p chimera-cli -- render speech|text|fi|song|notes|beatbox|creature|vowels …
cargo run --release -p chimera-cli -- diagnose       # nasal leakage, formants, bandwidths, pitch
cargo run --release -p chimera-cli -- compare csd    # against a real singer (docs/csd-comparison.md)
bun tools/spectrogram.ts in.wav out.png
```

## Docs

- [docs/architecture.md](docs/architecture.md): the acoustic model (FDTD airway, sources,
  anatomy, gestures).
- [docs/rust-engine.md](docs/rust-engine.md): the engine's real-time and determinism contract,
  and the browser boundary.
- [docs/ui-redesign.md](docs/ui-redesign.md) and [docs/mockups/](docs/mockups/): the vector
  display look.
- [docs/csd-comparison.md](docs/csd-comparison.md): scoring the voice against the Children's
  Song Dataset.
- [docs/hill-climb/](docs/hill-climb/): the rules and log for tuning the voice one measured
  step at a time.

Agents: see [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE). Bundled third-party files keep their own licenses: the CMU Pronouncing
Dictionary ([public/data/CMUDICT-LICENSE.txt](public/data/CMUDICT-LICENSE.txt)) and the fonts
([public/fonts/](public/fonts/)).
