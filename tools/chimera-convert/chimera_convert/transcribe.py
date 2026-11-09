"""Sung pitch -> notes, before and without the lyrics.

The pitch tracker gives a wobbly line: vibrato, scoops into notes, a singer whose tuning drifts
during a song. Rounding each moment to the nearest semitone turns that into notes that flicker or
flip a semitone when the singer goes flat. This module instead:

1. follows the singer's own tuning (`tuning`): the offset of their pitch from the A440 grid,
   averaged over a few seconds, so a choir sliding 40 cents flat stays on the same notes;
2. finds the notes with a hidden Markov model (`notes_hmm`), one state per semitone plus silence:
   a note stays put through vibrato and short consonant gaps, and changing note costs something,
   so glides and wobbles don't become notes of their own (the idea of pYIN's / Tony's note
   tracking);
3. marks where a note could be split for a repeated note on the same pitch (an unvoiced gap or a
   dip in loudness: "twin-kle" on one pitch).

The output is a list of `Segment`s; `assign.py` puts the syllables on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

HOP = 0.01


@dataclass
class Frames:
    """The frame-level analysis, every HOP seconds."""

    midi: np.ndarray
    """pitch in MIDI notes (NaN where there is none)"""
    voiced: np.ndarray
    """0..1: how sure we are that someone is singing a pitch here"""
    db: np.ndarray
    """loudness, dB below the loudest frame"""
    clear: np.ndarray | None = None
    """0..1: a clear pitch (the tracker's periodicity alone); `voiced` when not given"""

    @property
    def n(self) -> int:
        return len(self.midi)


@dataclass
class Segment:
    start: float
    end: float
    midi: float
    """the note, on the A440 grid after removing the singer's tuning"""
    cents: float
    """what was actually sung around that note (median, relative to `midi`, in cents)"""
    after_rest: bool
    """a silence of at least `rest` seconds comes before it (a breath, a phrase break)"""
    soft: bool = False
    """the same pitch as the segment before, split at a gap or loudness dip (a repeated note)"""


@dataclass
class Transcription:
    segments: list[Segment]
    tuning: np.ndarray
    """the singer's offset from A440 per frame (semitones, -0.5..0.5)"""
    frames: Frames
    breaks: list[float] = field(default_factory=list)


@dataclass
class Detection:
    """What counts as singing (the thresholds the app lets the user set before the notes are made).

    A frame is singing when it is louder than `gate_db` (dB below the loudest moment) and either
    has a clear pitch (the tracker's periodicity above `clarity`) or, with `rough` > 0, is simply
    loud: rough, shouted or distorted singing has no clear pitch, but on a separated voice track
    loudness alone is the voice (its pitch is then the tracker's best guess)."""

    gate_db: float = -38.0
    clarity: float = 0.15
    rough: float = 0.0
    hold: float = 0.4
    """a syllable is held over a gap in the singing shorter than this (s): a consonant, a moment
    the tracker lost the voice; longer gaps are rests (assign.hold_over_gaps)"""

    def to_dict(self) -> dict:
        return {"gate_db": round(float(self.gate_db), 1), "clarity": round(float(self.clarity), 3), "rough": round(float(self.rough), 3),
                "hold": round(float(self.hold), 3)}

    @staticmethod
    def from_dict(d: dict | None) -> "Detection":
        d = d or {}
        return Detection(float(np.clip(d.get("gate_db", -38.0), -80, 0)), float(np.clip(d.get("clarity", 0.15), 0, 0.9)),
                         float(np.clip(d.get("rough", 0.0), 0, 1)), float(np.clip(d.get("hold", 0.4), 0, 2)))


def level_db(rms: np.ndarray) -> np.ndarray:
    return 20 * np.log10(rms / (np.max(rms) + 1e-12) + 1e-12)


def suggest(rms: np.ndarray, voice_only: bool) -> Detection:
    """Thresholds for a recording: on a voice track (separated, or recorded alone) the level that
    best splits singing from the rest (Otsu, 2 dB lower so soft singing stays in) and loud
    rough singing counted; on a full mix only a clear pitch counts (the band is loud too)."""
    if not voice_only:
        return Detection(-38.0, 0.15, 0.0)
    x = np.clip(level_db(rms), -80, 0)
    h, e = np.histogram(x, bins=80, range=(-80, 0))
    c = (e[:-1] + e[1:]) / 2
    best, thr = -1.0, -38.0
    for k in range(1, 80):
        w0, w1 = h[:k].sum(), h[k:].sum()
        if w0 == 0 or w1 == 0:
            continue
        m0, m1 = (h[:k] * c[:k]).sum() / w0, (h[k:] * c[k:]).sum() / w1
        v = w0 * w1 * (m0 - m1) ** 2
        if v > best:
            best, thr = v, float(e[k])
    return Detection(float(np.clip(thr - 2, -50, -15)), 0.12, 0.6)


def frames_from(f0_hz: np.ndarray, periodicity: np.ndarray, rms: np.ndarray, gate_db: float = -38.0,
                clarity: float = 0.15, rough: float = 0.0) -> Frames:
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69 + 12 * np.log2(f0_hz / 440.0)
    n = min(len(midi), len(periodicity), len(rms))
    midi, per, rms = midi[:n], periodicity[:n], rms[:n]
    db = level_db(rms)
    # voicing: periodicity from the tracker (or, `rough`, loudness alone), faded out in quiet
    # frames (bleed, reverb tails)
    clear = np.clip((per - clarity) / 0.45, 0, 1)
    loud = np.clip((db - gate_db) / 8.0, 0, 1)
    v = loud * np.maximum(clear, rough)
    midi = np.where(np.isfinite(midi) & (f0_hz > 0), midi, np.nan)
    v = np.where(np.isnan(midi), 0.0, v)
    clear = np.where(np.isnan(midi), 0.0, clear * loud)
    return Frames(midi, v, db, clear)


def frames_with(f0_hz: np.ndarray, periodicity: np.ndarray, rms: np.ndarray, det: Detection) -> Frames:
    return frames_from(f0_hz, periodicity, rms, det.gate_db, det.clarity, det.rough)


def _smooth(x: np.ndarray, w: np.ndarray, sigma: float) -> np.ndarray:
    """Weighted Gaussian smoothing (NaN-free x)."""
    from scipy.ndimage import gaussian_filter1d

    num = gaussian_filter1d(x * w, sigma, mode="constant")
    den = gaussian_filter1d(w, sigma, mode="constant")
    return num / np.maximum(den, 1e-9)


def _box(x: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same") if len(x) >= n else x.astype(float)


def tuning(fr: Frames, window_s: float = 6.0) -> np.ndarray:
    """The singer's offset from the A440 semitone grid, frame by frame (semitones, continuous).
    A circular mean of the pitch's fractional part, over steady sung frames (vibrato averages out),
    smoothed over `window_s`."""
    # vibrato first averaged out over about one cycle (a circular mean of a pitch swinging
    # ±40 cents around a note has almost no direction), then steady frames only (not glides)
    m = np.nan_to_num(fr.midi)
    # only a clear pitch says where the singer's tuning is (not rough singing's guesses)
    vw = ((fr.clear if fr.clear is not None else fr.voiced) > 0.5).astype(float)
    mm = _box(m * vw, 19) / np.maximum(_box(vw, 19), 1e-9)
    d = np.abs(np.gradient(mm))
    w = vw * (d < 0.03) * (_box(vw, 19) > 0.99)
    ang = 2 * np.pi * (mm - np.round(mm))
    sigma = window_s / HOP / 2
    c = _smooth(np.cos(ang), w, sigma)
    s = _smooth(np.sin(ang), w, sigma)
    # where there is too little singing nearby, the offset is carried over from the singing around
    strength = np.hypot(c, s)
    ok = strength > 0.2
    if not ok.any():
        return np.zeros(fr.n)
    off = np.unwrap(np.arctan2(s, c)[ok]) / (2 * np.pi)
    # continuous: a singer drifting past half a semitone stays on the same notes
    out = np.interp(np.arange(fr.n), np.flatnonzero(ok), off)
    return out - np.round(np.median(out))


def notes_hmm(fr: Frames, tune: np.ndarray, p_change: float = 0.01, p_off: float = 0.015, p_on: float = 0.08,
              sigma: float = 0.38) -> np.ndarray:
    """The note sung in each frame (MIDI on the grid), or NaN for silence. Viterbi over
    silence + one state per semitone in the song's range."""
    x = fr.midi - tune
    good = fr.voiced > 0.3
    if not good.any():
        return np.full(fr.n, np.nan)
    lo = int(np.floor(np.nanpercentile(x[good], 0.5))) - 1
    hi = int(np.ceil(np.nanpercentile(x[good], 99.5))) + 1
    pitches = np.arange(lo, hi + 1)
    P = len(pitches)
    v = np.clip(fr.voiced, 1e-3, 1 - 1e-3)
    xs = np.nan_to_num(x, nan=-100.0)
    # emissions: silence vs each pitch; a heavy-tailed pitch likelihood (vibrato, scoops)
    d = xs[:, None] - pitches[None, :]
    like = 0.8 * np.exp(-0.5 * (d / sigma) ** 2) / sigma + 0.2 * np.exp(-0.5 * (d / 1.6) ** 2) / 1.6
    like = like / np.sqrt(2 * np.pi)
    # an unvoiced frame inside a note (a consonant) is possible but less likely than silence
    e_pitch = np.log(v[:, None] * like + (1 - v[:, None]) * 0.25 + 1e-12)
    e_sil = np.log((1 - v) + 0.02)
    E = np.concatenate([e_sil[:, None], e_pitch], axis=1)  # state 0 = silence
    # transitions
    S = P + 1
    T = np.full((S, S), -np.inf)
    T[0, 0] = np.log(1 - p_on)
    T[0, 1:] = np.log(p_on / P)
    T[1:, 0] = np.log(p_off)
    # changing note: nearer intervals more likely
    iv = np.abs(pitches[:, None] - pitches[None, :])
    w = np.exp(-iv / 5.0)
    np.fill_diagonal(w, 0)
    w = w / w.sum(1, keepdims=True)
    T[1:, 1:] = np.log(p_change * w + 1e-300)
    np.fill_diagonal(T[1:, 1:], np.log(1 - p_change - p_off))
    n = fr.n
    back = np.zeros((n, S), np.int16)
    score = E[0] + np.log(1.0 / S)
    for t in range(1, n):
        cand = score[:, None] + T
        back[t] = np.argmax(cand, axis=0)
        score = cand[back[t], np.arange(S)] + E[t]
    path = np.zeros(n, np.int64)
    path[-1] = int(np.argmax(score))
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    out = np.where(path == 0, np.nan, pitches[np.maximum(path - 1, 0)].astype(float))
    return out


def _runs(a: np.ndarray) -> list[tuple[int, int, float]]:
    """Runs of equal values (NaN runs skipped): (start, end_exclusive, value)."""
    runs = []
    i, n = 0, len(a)
    while i < n:
        if np.isnan(a[i]):
            i += 1
            continue
        j = i
        while j < n and a[j] == a[i]:
            j += 1
        runs.append((i, j, float(a[i])))
        i = j
    return runs


def segments(fr: Frames, tune: np.ndarray, path: np.ndarray, min_note: float = 0.1, min_alone: float = 0.05, rest: float = 0.25,
             gap: float = 0.04, dip_db: float = 6.0) -> list[Segment]:
    runs = _runs(path)
    # a short run touching another note is a blip in it (a glide, a tracker flip): it joins the
    # note before; a short run on its own is a short sung note (fast syllables between
    # consonants) unless it is shorter than a syllable can be
    keep = []
    for k, (a, b, p) in enumerate(runs):
        touching_next = k + 1 < len(runs) and runs[k + 1][0] == b
        if (b - a) * HOP >= min_note:
            keep.append([a, b, p])
        elif keep and keep[-1][1] == a:
            keep[-1][1] = b
        elif touching_next:
            runs[k + 1] = (a, runs[k + 1][1], runs[k + 1][2])
        elif (b - a) * HOP >= min_alone:
            keep.append([a, b, p])
    # a short passing tone between two touching notes (a glide from one to the other) joins the
    # note it leads into
    k = 1
    while k < len(keep) - 1:
        a, b, p = keep[k]
        pa, pb = keep[k - 1][2], keep[k + 1][2]
        if (b - a) * HOP < 0.15 and keep[k - 1][1] == a and keep[k + 1][0] == b and min(pa, pb) < p < max(pa, pb):
            keep[k + 1][0] = a
            del keep[k]
        else:
            k += 1
    out: list[Segment] = []
    prev_end = -1e9
    x = fr.midi - tune
    for a, b, p in keep:
        # split at unvoiced gaps and loudness dips inside the run (repeated notes)
        cuts = [a]
        unv = fr.voiced[a:b] < 0.3
        i = a
        while i < b:
            if unv[i - a]:
                j = i
                while j < b and unv[j - a]:
                    j += 1
                if (j - i) * HOP >= gap and i - cuts[-1] >= int(min_note / HOP) and b - j >= int(min_note / HOP):
                    cuts.append(j)
                i = j
            else:
                i += 1
        # loudness dips: a local minimum 'dip_db' below the maxima on both sides within 150 ms
        db = fr.db[a:b]
        w = int(0.15 / HOP)
        for c in range(w, len(db) - w):
            if db[c] == db[c - w:c + w + 1].min() and db[c - w:c].max() - db[c] >= dip_db and db[c + 1:c + w + 1].max() - db[c] >= dip_db:
                t = a + c
                if all(abs(t - q) >= int(min_note / HOP) for q in cuts) and b - t >= int(min_note / HOP):
                    cuts.append(t)
        cuts = sorted(cuts) + [b]
        for k in range(len(cuts) - 1):
            s, e = cuts[k], cuts[k + 1]
            seg = x[s:e]
            seg = seg[~np.isnan(seg)]
            cents = float(np.median(seg - p) * 100) if len(seg) else 0.0
            start, end = s * HOP, e * HOP
            out.append(Segment(start, end, p, cents, after_rest=start - prev_end >= rest, soft=k > 0))
            prev_end = end
    return out


def transcribe(fr: Frames, rest: float = 0.25) -> Transcription:
    tune = tuning(fr)
    path = notes_hmm(fr, tune)
    return Transcription(segments(fr, tune, path, rest=rest), tune, fr)
