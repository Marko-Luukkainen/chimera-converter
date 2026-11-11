"""Chimera's side: its syllable split (asked from its CLI) and the `render notes` JSON."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .lyrics import Token, Word
from .notes import Note

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi: float) -> str:
    r = int(round(midi))
    return f"{NOTE_NAMES[r % 12]}{r // 12 - 1}"


# ----------------------------------------------------------------------------- the Chimera CLI

def find_cli(repo: Path | None) -> tuple[list[str], Path] | None:
    """The `chimera` binary of a built checkout, or `cargo run` in it."""
    if repo is None or not (repo / "Cargo.toml").exists():
        return None
    for name in ("chimera.exe", "chimera"):
        exe = repo / "target" / "release" / name
        if exe.exists():
            return [str(exe)], repo
    if shutil.which("cargo"):
        return ["cargo", "run", "--release", "-q", "-p", "chimera-cli", "--"], repo
    return None


def cli_syllables(cli: tuple[list[str], Path], lyrics: str, lang: str = "en") -> list[str] | None:
    """Chimera's own syllables for `lyrics`, in order (their spelling chunks, "~" where it
    holds a word over more syllables). Chimera has no command for this, but `render notes`
    refuses a melody whose note count differs and lists the syllables it found; one note
    makes that happen for any lyrics of more than one syllable."""
    cmd, cwd = cli
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "probe.json"
        src.write_text(json.dumps({"bpm": 60, "lang": lang, "lyrics": lyrics, "notes": [[60, 1]]}), encoding="utf-8")
        p = subprocess.run(cmd + ["render", "notes", str(src), str(Path(tmp) / "probe"), "male"],
                           cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode == 0:
        return ["?"]  # exactly one syllable
    m = re.search(r"(\d+) syllables for 1 notes: ?(.*)", p.stderr)
    if not m:
        return None
    n = int(m.group(1))
    texts = m.group(2).split(" ") if n else []
    return texts if len(texts) == n else None


def group_by_word(words: list[Word], texts: list[str]) -> list[list[str]] | None:
    """Split Chimera's syllable list back into words: a word's chunks spell its parts out, and
    the "~" after them are its held syllables."""
    out: list[list[str]] = []
    i = 0
    for w in words:
        mine: list[str] = []
        for part in [p for p in w.text.split("-") if p]:
            low = part.lower()
            acc = ""
            while i < len(texts) and texts[i] != "~" and low.startswith(acc + texts[i].lower()) and acc != low:
                acc += texts[i].lower()
                mine.append(texts[i])
                i += 1
            if acc and acc != low:
                return None
            while acc and i < len(texts) and texts[i] == "~":
                mine.append("~")
                i += 1
        if not mine and re.search(r"[aeiouy]", w.text.lower()):
            return None  # a word with vowels always sings: the lists are out of step
        out.append(mine)
    return out if i == len(texts) else None


# ----------------------------------------------------------------------------- output

def lyrics_text(tokens: list[Token], words: list[Word], lang: str, melismas: dict[int, int] | None = None) -> str:
    """The lyrics for Chimera: the words in order with their phrase punctuation, Finnish words
    hyphenated, and a " -" for each melisma note. `melismas` counts melisma notes per syllable
    (global index). Chimera reads a melisma mark only between words, so a Finnish word with a
    melisma inside it is written in parts ("kis - sa"): its syllables are read the same either
    way. English melismas sit on a word's last syllable (merge_inner_melismas)."""
    mel = melismas or {}
    first = []  # global index of each word's first syllable
    k = 0
    for w in words:
        first.append(k)
        k += len(w.syls)
    out = ""
    for tk in tokens:
        if tk.kind == "punct":
            out = out.rstrip(" ")
            # a melisma mark needs space on both sides ("are - ." not "are -."), or Chimera
            # reads it as nothing
            out += (" " if out.endswith(" -") else "") + tk.text
            continue
        w = words[tk.word]
        g0 = first[tk.word]
        if lang == "fi" and w.syls:
            parts, cur = [], ""
            for si, sy in enumerate(w.syls):
                cur = sy.text if not cur else cur + "-" + sy.text
                m = mel.get(g0 + si, 0)
                if m:
                    parts.append(cur + " -" * m)
                    cur = ""
            if cur:
                parts.append(cur)
            text = " ".join(parts)
        else:
            m = sum(mel.get(g0 + si, 0) for si in range(len(w.syls)))
            text = w.text + " -" * m
        sep = "" if (not out or out.endswith("\n")) else " "
        out += sep + text
    return out.strip()


def merge_inner_melismas(notes: list[Note], syl_word: list[tuple[int, int]], words: list[Word], log=print) -> list[Note]:
    """Chimera only takes a melisma ("-") between words, so a pitch change inside a word (on any
    syllable but the last) is folded into its note, which keeps the longer pitch."""
    out: list[Note] = []
    head = None
    merged = 0
    for n in notes:
        if n.syl is not None:
            head = n.syl
            out.append(Note(n.start, n.end, n.midi, n.syl))
            continue
        if head is None:
            continue
        wi, si = syl_word[head]
        if si < len(words[wi].syls) - 1:
            prev = out[-1]
            if n.end - n.start > prev.end - prev.start:
                prev.midi = n.midi
            prev.end = n.end
            merged += 1
        else:
            out.append(Note(n.start, n.end, n.midi, None))
    if merged:
        log(f"note: {merged} pitch change(s) inside a word folded into one note (Chimera's melisma mark goes between words)")
    return out


def events(notes: list[Note], rest: float, transpose: float, keep_cents: bool) -> tuple[list[list[float]], float]:
    """[[midi, beats], ...] at 60 bpm (a beat is a second), rests as midi 0; and t0."""
    ev: list[list[float]] = []
    for i, n in enumerate(notes):
        p = n.midi + transpose
        p = round(p, 2) if keep_cents else float(round(p))
        a = round(n.start, 3)
        if i + 1 < len(notes):
            nxt = round(notes[i + 1].start, 3)
            e = round(n.end, 3)
            if nxt - e >= rest:
                ev.append([p, round(e - a, 3)])
                ev.append([0, round(nxt - e, 3)])
            else:
                ev.append([p, round(nxt - a, 3)])
        else:
            ev.append([p, round(max(n.end - a, 0.1), 3)])
    return ev, round(notes[0].start, 3) if notes else 0.3


def write_csv(path: Path, notes: list[Note], syl_text: list[str], transpose: float) -> None:
    lines = ["start_s,end_s,note,midi,syllable"]
    for n in notes:
        s = "~" if n.syl is None else syl_text[n.syl]
        lines.append(f"{n.start:.3f},{n.end:.3f},{note_name(n.midi + transpose)},{n.midi + transpose:.2f},{s}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path, data: dict) -> None:
    """Readable JSON: one note per line; a speech file: one syllable per line, each contour on one."""
    if "notes" not in data:
        big = ("syllables", "f0", "level")
        head = json.dumps({k: v for k, v in data.items() if k not in big}, ensure_ascii=False, indent=2)
        parts = [head[:-2]]
        if "syllables" in data:
            parts.append('  "syllables": [\n' + ",\n".join("    " + json.dumps(x) for x in data["syllables"]) + "\n  ]")
        for k in ("f0", "level"):
            if k in data:
                parts.append(f'  "{k}": ' + json.dumps(data[k], separators=(",", ":")))
        path.write_text(",\n".join(parts) + "\n}\n", encoding="utf-8")
        return
    head = json.dumps({k: v for k, v in data.items() if k != "notes"}, ensure_ascii=False, indent=2)
    notes = ",\n".join("    " + json.dumps(n) for n in data["notes"])
    path.write_text(head[:-2] + ',\n  "notes": [\n' + notes + "\n  ]\n}\n", encoding="utf-8")


def default_repo() -> Path | None:
    env = os.environ.get("CHIMERA_REPO")
    if env:
        return Path(env)
    # the checkout this converter sits in (tools/chimera-convert), wherever it was copied
    here = Path(__file__).resolve().parents[3]
    if (here / "Cargo.toml").exists() and (here / "crates").is_dir():
        return here
    home = Path.home() / "chimera-vocal-synth"
    return home if home.exists() else None
