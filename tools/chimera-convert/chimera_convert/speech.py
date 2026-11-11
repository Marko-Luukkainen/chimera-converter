"""Speech: the recording's timing, pitch and loudness, said by Chimera's speech planner (`--style speech`).

Singing and rap become notes that Chimera sings. Speech is not sung: a note per syllable flattens
the intonation into steps, and the song planner holds vowels and adds vibrato. So speech goes
to Chimera's speech planner instead (`chimera render spoken`), which keeps the language's own
articulation, aspiration and quantity and takes from the recording:

1. **Timing**: each syllable's vowel onset and end, found as in rap (words first: the alignment,
   then the onsets moved onto the vowels' rises, `rap.place`). A silence of at least `rest` is
   a pause; Chimera breathes there.
2. **Pitch**: the speaker's F0 contour every 10 ms (the clear frames, octave slips dropped,
   gaps held), as intervals from the speaker's median: at the chosen voice's own range
   (`pitch="voice"`: a male voice speaks a woman's intonation an octave down) or at the
   speaker's own pitch (`pitch="speaker"`); `expression` scales the intervals (1 = as spoken).
3. **Loudness**: the level contour, relative to the loud end of the speech, so stressed and
   emphasised syllables stay as strong as they were said; `dynamics` scales it.

The notes the editor shows are one per syllable at its median pitch. Moving a syllable stretches
the contours with it; raising or lowering it shifts its stretch of the pitch contour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .notes import Note
from .transcribe import HOP

PITCHES = ("voice", "speaker")
VOICE_HZ = {"male": 112.0, "female": 205.0, "child": 250.0, "neanderthal": 100.0}
"""each voice's speaking pitch (Chimera's speech defaults, render_phrases)"""
DB_PER_DECADE = 28.0
"""Chimera's output level per decade of breath drive (measured: drive 1 -> 0.55 is -7.3 dB)"""
LEVEL_STRENGTH = 3.0
"""the level gestures' strength against the planner's own breath (spoken.rs LEVEL_STRENGTH)"""
LEVEL_GAIN = 1.25
"""the share of a syllable's level difference given to the breath. Calibrated by a round trip of
Chimera's own speech with three syllables 5.3 dB louder than the rest: without a level contour
they came out 1.8 dB quieter (the vowels' own loudness), with a gain of 1.0 3.9 dB louder, 1.5
7.0 dB; 1.25 gives about the 5.3 spoken."""


@dataclass
class Opts:
    rest: float = 0.25
    """a silence at least this long (s) before the next syllable is a pause"""
    window: float = 0.08
    """how far (s) an onset may move onto its vowel's rise"""
    min_rise: float = 4.0
    """the rise (dB per 20 ms) that starts a vowel"""
    nucleus: float = 0.7
    """the part of a syllable whose pitch the editor shows as its note"""
    pitch: str = "voice"
    """"voice": the intonation at the chosen voice's range; "speaker": at the speaker's own pitch"""
    expression: float = 1.0
    """pitch intervals scaled (0.5 flatter, 1.5 livelier)"""
    dynamics: float = 1.0
    """loudness differences scaled (0 even, 1 as spoken)"""

    LIMITS = {"rest": (0.05, 1.5), "window": (0.0, 0.2), "min_rise": (1.0, 15.0), "nucleus": (0.2, 1.0),
              "expression": (0.0, 2.0), "dynamics": (0.0, 2.0)}

    def to_dict(self) -> dict:
        return {**{k: round(float(getattr(self, k)), 3) for k in self.LIMITS}, "pitch": self.pitch}

    @staticmethod
    def from_dict(d: dict | None) -> "Opts":
        o = Opts()
        for k, (lo, hi) in Opts.LIMITS.items():
            if d and d.get(k) is not None:
                setattr(o, k, float(np.clip(float(d[k]), lo, hi)))
        if d and d.get("pitch") in PITCHES:
            o.pitch = d["pitch"]
        return o

    def rap(self):
        """The placement's settings (the rap style's words-first placement)."""
        from .rap import Opts as RapOpts

        return RapOpts(rest=self.rest, window=self.window, min_rise=self.min_rise, nucleus=self.nucleus)


@dataclass
class Contours:
    """What the speech file is made from, every HOP s of the recording."""

    hz: np.ndarray
    """the speaker's F0 (Hz, NaN where there is none)"""
    db: np.ndarray
    """level, dB below the loudest frame"""

    def save(self, path: Path) -> None:
        np.savez_compressed(path, hz=self.hz.astype(np.float32), db=self.db.astype(np.float32))

    @staticmethod
    def load(path: Path) -> "Contours":
        d = np.load(path)
        return Contours(d["hz"].astype(float), d["db"].astype(float))


def contours(hz: np.ndarray, clear: np.ndarray, db: np.ndarray) -> Contours:
    """The speaker's F0 from the tracker's clear frames: a 5-frame median in semitones, and frames
    more than 7 semitones from the median of the second around them dropped (octave slips, a
    creak read as an octave down)."""
    n = min(len(hz), len(clear), len(db))
    hz, clear, db = np.asarray(hz[:n], float), np.asarray(clear[:n], float), np.asarray(db[:n], float)
    ok = (clear > 0.3) & (hz > 0)
    st = np.where(ok, 12 * np.log2(np.where(ok, hz, 1.0) / 100.0), np.nan)
    sm = st.copy()
    for i in np.flatnonzero(ok):
        sm[i] = np.nanmedian(st[max(0, i - 2): i + 3])
    w = int(0.5 / HOP)
    good = np.isfinite(sm)
    for i in np.flatnonzero(good):
        around = sm[max(0, i - w): i + w + 1]
        if abs(sm[i] - np.nanmedian(around)) > 7:
            good[i] = False
    out = np.where(good, 100.0 * 2 ** (np.nan_to_num(sm) / 12), np.nan)
    return Contours(out, db)


def default_body(c: Contours) -> str:
    v = c.hz[np.isfinite(c.hz)]
    return "male" if len(v) == 0 or np.median(v) < 165 else "female"


@dataclass
class Spoken:
    data: dict
    """the speech file for `chimera render spoken`"""
    warnings: list[str] = field(default_factory=list)
    syllables: int = 0
    pauses: int = 0


def _spans(ns: list[Note]) -> list[tuple[float, float]]:
    """Each syllable's (start, end) from its notes (a syllable is one note in speech)."""
    spans: dict[int, list[float]] = {}
    for n in ns:
        if n.syl is not None:
            spans[n.syl] = [n.start, n.end]
        elif spans:
            spans[max(spans)][1] = n.end
    return [tuple(spans[k]) for k in sorted(spans)]


def _warp(new: list[tuple[float, float]], old: list[tuple[float, float]]):
    """Time in the edited speech -> time in the recording: piecewise linear through every
    syllable's start and end (identity before and after)."""
    a, b = [0.0], [0.0]
    for (n0, n1), (o0, o1) in zip(new, old):
        for x, y in ((n0, o0), (n1, o1)):
            if x > a[-1] + 1e-6 and y > b[-1] + 1e-6:
                a.append(x)
                b.append(y)
    a.append(a[-1] + 1000.0)
    b.append(b[-1] + 1000.0)
    xa, xb = np.array(a), np.array(b)
    return lambda t: np.interp(t, xa, xb)


def build(ns: list[Note], auto: list[Note], lyr, c: Contours, o: Opts, body: str, transpose: float = 0.0,
          source: str = "", cli=None, lyrics_text: str | None = None) -> Spoken:
    """The speech file from the (edited) notes, the notes as converted and the contours."""
    from . import chimera

    spans, old = _spans(ns), _spans(auto)
    if len(spans) != len(lyr.syl_word) or len(old) != len(spans):
        raise ValueError(f"{len(spans)} syllables in the notes for {len(lyr.syl_word)} in the lyrics")
    warp = _warp(spans, old)
    # pitch edits: a syllable's note against the converted one shifts its stretch of the contour
    head = {n.syl: n.midi for n in ns if n.syl is not None}
    head0 = {n.syl: n.midi for n in auto if n.syl is not None}
    end = spans[-1][1] + 0.5
    t = np.arange(0.0, end, HOP)
    src = np.clip(np.round(warp(t) / HOP).astype(int), 0, len(c.hz) - 1)
    hz = c.hz[src]
    shift = np.zeros(len(t))
    starts = np.array([s for s, _ in spans])
    k = np.clip(np.searchsorted(starts, t, side="right") - 1, 0, len(spans) - 1)
    for i in range(len(spans)):
        shift[k == i] = head.get(i, 0.0) - head0.get(i, 0.0)
    voiced = c.hz[np.isfinite(c.hz)]
    if len(voiced) == 0:
        raise ValueError("no pitch in the speech (is there a voice in the recording?)")
    center = float(np.median(voiced))
    st = 12 * np.log2(np.where(np.isfinite(hz), hz, center) / center) * o.expression
    base = VOICE_HZ.get(body.split("/")[0], 112.0) if o.pitch == "voice" else center
    out_hz = np.where(np.isfinite(hz), base * 2 ** ((st + shift + transpose) / 12), 0.0)
    # loudness: one level per syllable, its vowel's peak, relative to the loud end of what is said.
    # Not the level frame by frame: that also carries each vowel's own loudness and the dips of
    # the consonants, which Chimera makes itself, and they came out twice as deep (a round trip
    # of Chimera's own speech: syllable levels correlated 0.92 but spread twice as wide).
    peaks = []
    for (s0, s1) in old:
        i0, i1 = int(s0 / HOP), max(int(s0 / HOP) + 1, int(min(s1, s0 + 0.15) / HOP))
        seg = c.db[i0:i1]
        peaks.append(float(seg.max()) if len(seg) else -60.0)
    peaks = np.array(peaks)
    ref = float(np.percentile(peaks, 90)) if len(peaks) else 0.0
    rel_syl = np.clip(peaks - ref, -24.0, 0.0) * o.dynamics * LEVEL_GAIN
    rel = rel_syl[k]
    # ease between syllables over 40 ms (the contour's gestures interpolate between its points)
    rel = np.convolve(np.pad(rel, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    drive = 10 ** (rel / DB_PER_DECADE)
    # the planner's own breath (drive 1, weight 1) blends with the level (weight LEVEL_STRENGTH)
    level = np.clip(((1 + LEVEL_STRENGTH) * drive - 1) / LEVEL_STRENGTH, 0.05, 1.0)
    # the speech starts at least 0.3 s in, so the first word's consonants have room
    offset = max(0.0, 0.3 - spans[0][0])
    syl_times = [[round(a + offset, 3), round(b + offset, 3)] for a, b in spans]
    text = lyrics_text if lyrics_text is not None else chimera.lyrics_text(lyr.tokens, lyr.words, lyr.lang, {})
    data = {"kind": "spoken", "lang": lyr.lang, "lyrics": text, "body": body, "source": source,
            "pitch": o.pitch, "transpose": transpose,
            "syllables": syl_times,
            "f0": {"t0": round(offset, 3), "hop": HOP, "hz": [round(float(x), 1) for x in out_hz]},
            "level": {"t0": round(offset, 3), "hop": HOP, "v": [round(float(x), 3) for x in level]}}
    if offset > 0:
        data["offset"] = round(offset, 3)
    warnings = []
    if cli:
        check = chimera.cli_syllables(cli, text, lyr.lang)
        if check is not None and check != ["?"] and len(check) != len(spans):
            warnings.append(f"Chimera reads {len(check)} syllables for {len(spans)}; fix the lyrics (hyphens)")
    pauses = sum(1 for (a0, a1), (b0, _) in zip(spans, spans[1:]) if b0 - a1 >= o.rest)
    return Spoken(data, warnings, len(spans), pauses)


def seconds(data: dict) -> float:
    """How long the speech file runs (s)."""
    syl = data.get("syllables") or [[0, 0]]
    return float(syl[-1][1]) + 0.4
