# chimera-convert

Turns a sung recording (wav, mp3, flac …) and its lyrics into a CHIMERA melody file, which
`chimera render notes` sings.

```
recording ─► [Demucs: voice apart] ─► pitch (torchcrepe) ─► notes (HMM that follows the tuning) ─┐
                                    └► lyrics alignment (MMS, sung parts only) ─────────────────────┤
lyrics ─► words ─► syllables (Finnish: rules, English: Chimera's own split) ─────────────────────────┴► syllables on notes ─► .json
```

1. **Voice apart** (on by default, `--separate`): Demucs htdemucs separates the vocal track from
   the backing. Without it the pitch is tracked on the whole mix and the result is clearly worse.
2. **Pitch** every 10 ms: torchcrepe on the GPU (librosa's pYIN as the fallback).
3. **Notes before words** (`transcribe.py`): the singer's tuning is followed over the song (vibrato
   averaged out), so a singer drifting 40 cents flat stays on the same notes. Notes are found with
   a hidden Markov model (one state per semitone plus silence): a note holds through vibrato and
   short consonant gaps, and a glide or a flip doesn't become a note of its own. A repeated note is
   split at a gap or a dip in loudness.
4. **What counts as singing** (`transcribe.Detection`): louder than a level threshold and either a
   clear pitch or, on a voice track, loud enough alone (rough, shouted or distorted singing has no
   clear pitch). The app shows it and lets you set it before the notes are made.
5. **Syllables**: Finnish by its spelling rules, English by **Chimera's own split**.
6. **Alignment**: the multilingual MMS forced aligner says roughly when each syllable's vowel
   starts. Vowels are only allowed where someone sings, so the alignment can't drift into a solo.
7. **Syllables on notes** (`assign.py`): the whole song is solved at once by dynamic programming.
   A syllable starts at a note start (or a split of a repeated note), as near the model's time as
   possible; notes between one syllable and the next are its melisma; singing after a breath that
   no syllable needs (backing vocals, shouts) is dropped; a line break prefers a breath. A gap
   shorter than the hold time is a consonant and the syllable is held over it. A syllable with no
   singing to sit on is marked for checking in the editor.

The output uses 60 bpm, so one beat is one second and the note lengths are the recording's timing.

### Rap (`--style rap`)

Rap has few steady notes: the pitch glides like speech, one voiced run holds five to ten
syllables, and shouted lines have no clear pitch. Notes found first don't line up with the
syllables (in the tests, at 11 syllables a second the singing path puts syllables hundreds of
milliseconds off). The rap style turns the order around (`rap.py`):

1. **Words first**: the alignment places each syllable's vowel. Vowels are kept where the voice
   is: on a voice track its loudness, since the pitch tracker misses fast and rough syllables.
2. **Sharper onsets**: each onset moves onto a rise of the vowel band's energy (150-1200 Hz,
   5 ms frames) within 80 ms, matched for the whole song at once so two drifting onsets don't
   take the same vowel; a vowel is placed where its level comes within 12 dB of its peak. On
   synthetic flows of 6-11 syllables a second with the model 20-40 ms off, the worst error
   drops to about 3 ms. After a voiced consonant (l, m, n, r, j, v) or another vowel there is
   often no rise to find: those onsets keep the model's time (about a third on a real song).
3. **Pitch per syllable**: the median of the clear pitch over the syllable's vowel (its first
   70 %), kept to the cent. A whispered or shouted syllable takes its neighbours' pitch.
4. **One note per syllable** up to the next; a silence of 0.15 s or more is a rest. No melismas,
   no vibrato (0).

It needs the alignment (`--align mms`). A pitch glide inside a syllable is flattened to its
median: rhythm and timing are exact, intonation is one value per syllable.

What a real song showed (a 3:10 Finnish rap, 590 syllables, Quadro T2000):

- **Keep the ad-libs that are on the recording in the lyrics.** Without them the alignment
  spent chorus syllables on the ad-libs and one separator put a whole chorus line 5-8 s off.
  With them the three separators agreed on 94-97 % of the syllables to 50 ms.
- **Any separator works**; they agree outside the choruses. htdemucs took about 60 s for the
  whole conversion, htdemucs_ft 120 s, RoFormer 11 min (its separation alone 8.5 min).
- **`--lead-only` can remove a hook.** The karaoke model kept 98-99 % of the verses but 20-30 %
  of the choruses, sung there by other voices, and the chorus lyrics piled onto what was left.
  The converter now says where that happens; leave those lines out of the lyrics or don't use it.

**Language** is read from the lyrics (Finnish or English). When the words don't tell (too few,
both languages, or they look like another language such as Swedish), the converter asks: the app
shows a language choice, and the command line stops and asks for `--lang fi` or `--lang en`. You
can always choose it yourself.

## The app

`scripts\start_app.bat` starts the converter app at http://127.0.0.1:5320 and opens it in the
browser. Close the window to stop it.

1. **New song**: drop a recording and type the lyrics. The language is detected as you type
   (Language: Detect); if it is unsure, choose Finnish or English before converting. Choose
   "Separate the voice" for a finished song with its backing (and the separator: Demucs, Demucs
   fine-tuned or RoFormer; the lead voice alone). Style: Singing or Rap; Rap shows its settings:
   the shortest silence that is a rest, how far onsets move onto vowels, what rise starts a vowel,
   which part of a syllable gives its pitch, and pitch to the cent. In the editor, Style "Change…"
   switches between singing and rap or changes the rap settings: the notes are made again from
   the analysis already made, in seconds (edits are lost).
2. **Conversion** shows its progress (the first run downloads the models). First the audio is
   analysed (separation, pitch, the alignment model), then it stops at **What counts as singing**:
   the level and the pitch clarity over the whole song, with a green strip for what counts as
   singing (grey: loud but not counted). Click the picture to listen there. Adjust if needed:
   - *Level threshold*: singing is louder than this (dB below the loudest moment). Lower it when
     quiet singing is missed.
   - *Pitch clarity needed*: how clear a pitch must be. Lower it for breathy or reverberant singing.
   - *Rough voice counts*: loud singing without a clear pitch (shouts, rasp, distortion) counts as
     singing. Separated voices (or a voice recorded alone) only; keep it at 0 on a full mix.
   - *Hold syllables over gaps*: a syllable is held over a gap shorter than this (words don't come
     out short), but the singer still breathes at a line break.
   **Make the notes →** makes the notes with these (a few seconds; the analysis is kept). The
   editor's **Singing…** comes back here; **Back to the notes** returns without changing anything.
   To skip this step, untick "Let me check what counts as singing" when adding the song.
3. **Editor**: a piano roll with the sung pitch (orange), syllable notes (blue) and melismas
   (pink). Drag a note up or down to change its pitch and by its edges to change its timing;
   Shift+drag moves it. Keys: S split, Delete merge with the previous, [ ] move a syllable to the
   previous or next note, ↑↓ pitch, Space play, Ctrl+Z undo. The language can be changed next to
   the title (the notes are placed again). Orange dashed notes are syllables that found no singing:
   "N to check ▸" in the status bar jumps to the next one.
4. **Open in Chimera (live)** opens the song in Chimera's own Sing mode (Chimera must be running:
   `start_chimera.bat`). There it plays on Chimera's engine in real time, and the voice controls
   work while it sings: Vibrato, Rate, Breathy and Ring (*Song* page), Bright and Transpose
   (*Tone* page), Pressed, Rough and Fry (Voice panel) and the body in the top bar
   (Male/Female/Child; a change restarts the song). Vibrato and Transpose take effect within about
   half a second, the others at once. The voice comes in at once (the recording's intro is
   skipped) and keeps singing in a background window.
5. **Sing with Chimera** renders the current notes to a file, with its progress shown; the playback
   source "Recording" / "Voice" / "Chimera" switches what you compare.
6. **Duet show…** makes a show for Chimera's duet page (`public\shows\<id>`, not in git): start
   Chimera (`start_chimera.bat`) and open `http://127.0.0.1:5317/?show=<id>`. The show page has
   two modes: **Recorded** plays the finished render, **Live voice** sings the song on Chimera's
   engine in the page itself over the backing (the recording without its voice, made when the
   voice was separated). The **Voice settings** panel picks the singer's character (Natural,
   Soft, Pop, Rock, Opera, Crooner, Folk) and body (Male/Female/Child or between), and sets
   vibrato, rate, transpose, looseness, bright, breathy, ring, pressed, rough, fry, growl, power
   and the voice and band levels, all heard at once. **+ Save voice** keeps a voice by name, and
   the show remembers the last voice it was sung with.
   **Download melody** gives the `render notes` file.

Songs are kept in `out\sessions\` (not in git). The UI's source is in `app\` (React + Vite, in
Chimera's look); `app\README.md` says how to rebuild it.

## Moving the setup to another Windows machine

From GitHub: run [`install_from_github.bat`](../../install_from_github.bat) on the new machine.

From a working copy (keeps local, uncommitted changes and your songs): run
`transfer_to_another_pc.bat` in the Chimera folder. It asks for a destination (USB stick, network
share or folder) and writes a `ChimeraTransfer` folder there: Chimera with its local changes and
commits, the built engine and `chimera.exe`, the converter with its app and, if you want, the
models (about 1.3 GB) and your songs. On the new machine run `ChimeraTransfer\INSTALL.bat`: it
installs what is missing with winget (Python 3.12, Bun), makes the converter's Python environment
(torch with CUDA on an NVIDIA GPU, else the CPU build), installs Chimera's packages and puts
"Chimera" and "Chimera Converter" on the desktop. Rust is only needed to change the engine
(`INSTALL.bat -Dev`).

## Install (Windows, NVIDIA)

Python 3.12 or 3.11 (Demucs's dependencies may not have 3.13 packages yet). The converter lives in
the Chimera repo at `tools\chimera-convert`.

```powershell
cd <chimera repo>\tools\chimera-convert
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

`scripts\install.bat` does the same (the CPU build of torch when there is no NVIDIA GPU), checks
the install and runs the tests.

Check that the GPU is found: `python -c "import torch; print(torch.cuda.is_available())"`.

For English, build Chimera's CLI once at the repo root (the syllable split comes from it):

```powershell
cd <chimera repo>
cargo build --release -p chimera-cli
```

The first run downloads the models: the MMS aligner, about 1.2 GB (Hugging Face), and Demucs,
about 80 MB. They are cached.

Optional, for cleaner vocals (`--separator roformer`) and the lead voice apart from backing vocals
and ad-libs (`--lead-only`), the audio-separator package, with the same CUDA index as torch:

```powershell
pip install -r requirements-separator.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

Without the index pip takes audio-separator's torchvision from PyPI, and with it a CPU torch in
place of the CUDA one. The file pins torchvision for torch 2.11; for another torch, change it
(torchvision 0.N+15 goes with torch 2.N). The Mel-Band RoFormer models download on first use and
are cached in `%USERPROFILE%\.cache\chimera-convert\separator-models`.

## Command line

Keep conversions in `out\`: it is outside git, so files made from recordings stay out of the repo.

```powershell
# a cappella, or a vocal track already separated
python -m chimera_convert song.wav lyrics.txt -o out\song.json

# a finished song with its backing: the voice is separated first
python -m chimera_convert song.mp3 lyrics.txt --separate --plot -o out\song.json

# English, language chosen; Chimera is found from the repo this sits in, $CHIMERA_REPO or --chimera PATH
python -m chimera_convert song.mp3 lyrics.txt --lang en --separate -o out\song.json

# rap: words first, one note per syllable
python -m chimera_convert track.mp3 lyrics.txt --style rap --separate --plot -o out\track.json
```

Then in Chimera (at the repo root):

```powershell
.\target\release\chimera.exe render notes tools\chimera-convert\out\song.json song-chimera female
```

### Outputs

| File | Contents |
|---|---|
| `song.json` | Chimera's melody file: `bpm`, `lyrics`, `notes: [[midi, beats], …]` (midi 0 is a rest), `t0`, `vibrato`, `lang`, and for reference `source` and `body`. |
| `song.csv` | The notes for checking: start, end, pitch, syllable. |
| `song.png` | (`--plot`) The sung pitch, the notes and the syllables in one picture: the quickest way to see whether the alignment landed. |
| `song.vocals.wav` | (`--separate`) The separated vocal track. Listen to it when the result looks odd. |

### Options

| Option | Default | Meaning |
|---|---|---|
| `--lang auto\|fi\|en` | `auto` | the lyrics' language; `auto` reads it from the words and stops to ask when unsure |
| `--style sing\|rap` | `sing` | `rap`: words first, one note per syllable at the pitch inside it (see Rap) |
| `--separate` | off | separate the voice from the backing first |
| `--separator htdemucs\|htdemucs_ft\|roformer` | `htdemucs` | with `--separate`: `htdemucs_ft` is cleaner and about 4x slower; `roformer` the cleanest (requirements-separator.txt) |
| `--lead-only` | off | with `--separate`: the lead voice alone, without backing vocals, doubles and ad-libs (requirements-separator.txt); warns where it drops a hook sung by other voices |
| `--voice-only` | off | the recording is a voice alone (implied by `--separate`) |
| `--gate DB`, `--clarity X`, `--rough X`, `--hold S` | suggested | what counts as singing (see the app's step 2) |
| `--align mms\|none` | `mms` | `none`: no alignment, syllables on notes in order (light, but fragile) |
| `--pitch crepe\|pyin` | crepe | pitch tracker |
| `--transpose N` | 0 | semitones, e.g. `-12` for a female part sung by a male voice |
| `--keep-cents`, `--no-keep-cents` | off (rap: on) | keep the sung pitch to the cent instead of the nearest note |
| `--vibrato C` | 35 (rap: 0) | vibrato depth written to the file, in cents |
| `--rest S` | 0.25 (rap: 0.15) | the shortest silence written as a rest |
| `--rap-window MS`, `--rap-rise DB`, `--rap-nucleus F` | 80, 4, 0.7 | rap: how far an onset moves onto its vowel, the rise (dB per 20 ms) that starts a vowel, the part of a syllable that gives its pitch |

## The lyrics file

- UTF-8 text. Line breaks, commas and full stops mark breaths.
- Write the words **exactly as they are sung**: choruses written out, no "×2", no spoken shouts
  that aren't in the recording, and the ad-libs that are (rap lyrics sites put them in
  parentheses: keep the words, the parentheses don't matter).
- Loan words and abbreviations are split by Finnish spelling in a Finnish song: write them as
  they are said (`äm-sii` for MC, `boi` for boy), or a vowelless word like "MC" gets no syllable.
- Finnish compounds are split right only when the boundary is marked: `kesä-yö`,
  `rakkaus-laulu`. A hyphen also forces any other split.
- Melismas need no marking; the converter reads them from the melody.
- One language per song. When the lyrics mix Finnish and English, the converter asks which one
  the song is sung in (the other language's words are then said by its rules).

## Limits

- Finnish words are written pre-split (`kis-sa`) and the converter checks the syllable count
  against Chimera at the end.
- Chimera's melisma mark `-` only works between words: a pitch change inside an English word
  (on any but its last syllable) is merged into one note, with the pitch of the longer part.
- One singer at a time. Backing vocals, harmonies and heavy reverb or autotune confuse the pitch
  tracking and the alignment.
- The alignment assumes the lyrics match the singing. A missing or extra line shifts every
  syllable after it.
- English syllable counts are certain only when Chimera is found and its
  `target\release\chimera.exe` is built; without it unknown words are guessed. The converter
  checks the count against Chimera at the end and warns when it doesn't match.
- Rap: the editor draws notes on the nearest semitone row, and dragging a note's pitch rounds it
  (the file keeps the cents until then). The separator is chosen when a song is added (it is part
  of the analysis); changing it means adding the song again.
- Files made from copyrighted recordings must not be added to Chimera's git repo (the repo's
  rule). Keep them in `out\` or outside the repo.

## Tests

```powershell
python -m pytest -q
```

The tests cover language detection, Finnish syllabification, reading Chimera's syllable split,
CTC alignment, note finding on synthetic singing (pitches, vibrato, legato, rests, melismas, a
pitch anticipated in a consonant, a singer drifting flat, rough singing), placing syllables on
notes, the rap style on synthetic fast flows (onsets on the vowels, pitch per syllable, a breath,
a whispered syllable), a whole run, and the app's server (conversion, the singing check, editing, rendering, show
export, language change). The UI's editing rules are tested in `app`: `bun run test`.

`scripts\smoke.bat` runs a round trip with the real models: Chimera sings its demo songs, the
converter reads them back and Chimera sings the result.
