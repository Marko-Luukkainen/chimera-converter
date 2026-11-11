"""Rap: words first, then the pitch from inside each syllable (`--style rap`).

The singing path (transcribe.py + assign.py) finds notes first and puts the syllables on their
starts. Rap has few steady notes: the pitch glides like speech intonation, one voiced run can hold
five to ten syllables, and shouted or compressed lines have no clear pitch. Notes found first
then don't line up with the syllables, and many syllables end up on "virtual" notes. Here the
order is turned around:

1. **Words**: the MMS alignment gives each syllable's vowel onset. Vowels are kept where the
   voice is (on a voice track its loudness, not the pitch tracker's voicing, which misses fast
   and rough syllables).
2. **Sharper onsets** (`refine`): each onset moves to a rise of the vowel band's energy
   (150-1200 Hz, 5 ms frames) within +-80 ms, matched for the whole song at once so that two
   drifting onsets don't take the same vowel. The model's frames are 20 ms and its boundaries
   drift by a few frames: at eight syllables a second that is a large part of a syllable. An
   onset with no rise to match keeps the model's time.
3. **Pitch per syllable** (`notes_for`): the median of the clear pitch over the syllable's
   first part (its vowel; the coda consonants come last). A syllable with no clear pitch
   (whispered, shouted) takes its pitch from its neighbours.
4. **One note per syllable**, from its onset to the next one. A silence of at least `rest`
   before the next onset becomes a rest; shorter gaps are consonants and the note is held.

No melismas and no note transcription: a pitch change inside a syllable is intonation, not a
new note, and is flattened to the syllable's median.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .notes import Note
from .transcribe import HOP, Frames

HOP_ENV = 0.005
"""the vowel band envelope's frame (s)"""
BAND = (150.0, 1200.0)


@dataclass
class Opts:
    rest: float = 0.15
    """a silence at least this long (s) before the next syllable is a rest"""
    window: float = 0.08
    """how far (s) an onset may move to a rise of the vowel band's energy"""
    min_rise: float = 4.0
    """the rise (dB over 20 ms) that counts as a vowel starting"""
    nucleus: float = 0.7
    """the part of a syllable (from its onset) whose pitch is its pitch"""
    last_max: float = 1.0
    """the longest the last syllable before the end of the song may sound (s)"""

    # the settings the app and the CLI let the user set, with their allowed ranges
    LIMITS = {"rest": (0.05, 1.0), "window": (0.0, 0.2), "min_rise": (1.0, 15.0), "nucleus": (0.2, 1.0)}

    def to_dict(self) -> dict:
        return {k: round(float(getattr(self, k)), 3) for k in self.LIMITS}

    @staticmethod
    def from_dict(d: dict | None) -> "Opts":
        """The user's settings, each clipped to its range; missing ones keep their defaults."""
        o = Opts()
        for k, (lo, hi) in Opts.LIMITS.items():
            if d and d.get(k) is not None:
                setattr(o, k, float(np.clip(float(d[k]), lo, hi)))
        return o


@dataclass
class Result:
    notes: list[Note]
    onsets: list[float]
    moved: int = 0
    """onsets the vowel band's energy moved"""
    doubtful: list[int] = field(default_factory=list)
    """syllables placed where there is no voice (worth a look in the editor)"""
    unpitched: int = 0
    """syllables with no clear pitch of their own"""


# ----------------------------------------------------------------------------- the audio

def vowel_envelope(y16: np.ndarray, sr: int = 16000) -> np.ndarray:
    """The vowel band's energy every 5 ms (dB below its loudest frame)."""
    n_fft, hop = 512, int(HOP_ENV * sr)
    y = np.asarray(y16, np.float32)
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    pad = n_fft // 2
    y = np.pad(y, (pad, pad))
    n = 1 + (len(y) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(y[idx] * np.hanning(n_fft)[None, :], axis=1)) ** 2
    f = np.fft.rfftfreq(n_fft, 1 / sr)
    e = spec[:, (f >= BAND[0]) & (f <= BAND[1])].sum(1)
    return 10 * np.log10(e / (e.max() + 1e-12) + 1e-12)


def presence(fr: Frames, gate_db: float, voice_only: bool) -> np.ndarray:
    """0..1 per 10 ms frame: is the voice there. On a voice track its loudness (fast, rough and
    unvoiced syllables included); on a full mix the band is loud too, so only a clear pitch."""
    if voice_only:
        return np.clip((fr.db - gate_db) / 8.0, 0, 1)
    return fr.voiced


# ----------------------------------------------------------------------------- the onsets

def ctc_onsets(words, lp: np.ndarray, frame: float, vocab: dict, blank: int, fr: Frames, voice: np.ndarray) -> list[float]:
    """Each syllable's vowel onset from the alignment, vowels kept where the voice is."""
    from . import assign

    pres = Frames(fr.midi, voice, fr.db, fr.clear)
    return assign.ctc_onsets(words, lp, frame, vocab, blank, pres)


def vowel_rises(env: np.ndarray, min_rise: float, reach: float = 12.0) -> np.ndarray:
    """Where a vowel starts: for each rise of the vowel band's energy of at least `min_rise` dB
    over 20 ms, the first moment it comes within `reach` dB of the loudest moment of the next
    150 ms. A rise that never gets that close is not a vowel (a fricative after silence leaks into
    the band, but stays well below the vowel that follows).

    Not the steepest point of the rise: a syllable often rises in two steps, its consonant and
    then its vowel, and the steepest step can be the consonant's (on a real song, such vowels
    were refused for being too quiet 15 ms past the steepest point). Where the rise starts within
    `reach` of the top already (a shallow dip between legato syllables), the steepest point."""
    n = len(env)
    rise = np.zeros(n)
    if n >= 5:
        rise[2:n - 2] = env[4:] - env[:-4]
    up = rise >= min_rise
    look = int(0.15 / HOP_ENV)
    out = []
    i = 0
    while i < n:
        if not up[i]:
            i += 1
            continue
        j = i
        while j < n and up[j]:
            j += 1
        a = max(0, i - 2)
        top = env[a:min(n, i + look)].max()
        hit = np.flatnonzero(env[a:min(n, j + 3)] >= top - reach)
        if len(hit):
            if env[a] >= top - reach:  # a shallow dip (legato): the steepest point
                seg = rise[i:j]
                top_i = np.flatnonzero(seg >= seg.max() - 1e-9)
                out.append((i + (top_i[0] + top_i[-1]) / 2) * HOP_ENV)
            else:
                out.append((a + hit[0]) * HOP_ENV)
        i = j
    return np.array(out)


def refine(onsets: list[float], env: np.ndarray | None, o: Opts = Opts(), min_gap: float = 0.04) -> tuple[list[float], int]:
    """Each onset moved onto a vowel's start (`vowel_rises`) within +-`o.window`, when one fits.

    The model's boundaries drift by a few of its 20 ms frames, up to a large part of a fast
    syllable, so the nearest rise is not always the syllable's own: two drifting onsets can both
    lie nearest one vowel. The whole song is matched at once (dynamic programming): syllables
    and rises in order, each rise to at most one syllable, a match costing (distance / window)^2
    and an onset left on the model's time costing as much as a match at the window's edge.
    Onsets stay in order, at least `min_gap` apart. Returns the onsets and how many moved."""
    out = [float(t) for t in onsets]
    if env is None or len(env) < 8 or not out:
        return out, 0
    peaks = vowel_rises(env, o.min_rise)
    P, K = len(peaks), len(out)
    if P == 0:
        return out, 0
    miss = 1.0
    # state: the last rise used (0: none yet, p + 1: rise p)
    dp = np.zeros(P + 1)
    dp[1:] = np.inf
    idx = np.arange(P + 1)
    back: list[dict[int, int]] = []  # per syllable: state -> the state before, where it matched
    for m in out:
        new = dp + miss  # left on the model's time: the state stays
        best = np.minimum.accumulate(dp)
        first = np.r_[True, dp[1:] < best[:-1]]
        arg = np.maximum.accumulate(np.where(first, idx, 0))  # where each running minimum is
        lo, hi = np.searchsorted(peaks, m - o.window), np.searchsorted(peaks, m + o.window, side="right")
        moves = {}
        for p in range(lo, hi):  # rise p after a state using a rise before it (states 0..p)
            c = best[p] + ((peaks[p] - m) / o.window) ** 2
            if c < new[p + 1]:
                new[p + 1] = c
                moves[p + 1] = int(arg[p])
        back.append(moves)
        dp = new
    s = int(np.argmin(dp))
    chosen = [-1] * K
    for k in range(K - 1, -1, -1):
        if s in back[k]:
            chosen[k] = s - 1
            s = back[k][s]
    moved = 0
    prev = -np.inf
    for k, p in enumerate(chosen):
        t = float(peaks[p]) if p >= 0 else out[k]
        t = max(t, prev + min_gap)
        moved += abs(t - onsets[k]) > 1e-9 and p >= 0
        out[k] = prev = t
    return out, moved


# ----------------------------------------------------------------------------- the notes

def _sound_end(voice: np.ndarray, a: float, b: float, rest: float, limit: float) -> float:
    """Where the syllable starting at `a` stops sounding before `b`: the start of the first
    silence of at least `rest` (or `b` when there is none)."""
    n = len(voice)
    i = int(np.ceil((a + 0.04) / HOP))
    stop = min(n, int(np.ceil(min(b, limit) / HOP)))
    need = max(1, int(round(rest / HOP)))
    run = 0
    while i < stop:
        if voice[i] < 0.3:
            run += 1
            if run >= need:
                return (i - run + 1) * HOP
        else:
            run = 0
        i += 1
    if b > limit:  # the song ends: the voice stops at its last loud frame
        loud = np.flatnonzero(voice[int(a / HOP):stop] >= 0.3)
        return a + (loud[-1] + 1) * HOP if len(loud) else min(b, a + 0.25)
    if run and i >= n:
        return (i - run) * HOP
    return b


def notes_for(onsets: list[float], fr: Frames, voice: np.ndarray, midi: np.ndarray, o: Opts = Opts()) -> Result:
    """One note per syllable: from its onset to the next (or to a rest), at the median of the
    clear pitch `midi` (NaN where there is none) over the syllable's vowel."""
    from .assign import tidy

    K = len(onsets)
    dur = fr.n * HOP
    doubtful, pitch, spans = [], np.full(K, np.nan), []
    for k, a in enumerate(onsets):
        b = onsets[k + 1] if k + 1 < K else np.inf
        end = _sound_end(voice, a, b, o.rest, min(dur, a + o.last_max) if k + 1 == K else np.inf)
        end = max(end, a + 0.06) if k + 1 == K else min(max(end, a + 0.06), b)
        spans.append((a, end))
        i0, i1 = int(max(0.0, a - 0.02) / HOP), int(min(dur, a + 0.12) / HOP) + 1
        if not len(voice[i0:i1]) or voice[i0:i1].max() < 0.3:
            doubtful.append(k)
        for part in (o.nucleus, 1.0):
            j0, j1 = int(round(a / HOP)), int(round((a + part * (end - a)) / HOP))
            vals = midi[j0:max(j1, j0 + 1)]
            vals = vals[np.isfinite(vals)]
            if len(vals) >= (3 if part < 1.0 else 2):
                pitch[k] = float(np.median(vals))
                break
    known = np.flatnonzero(np.isfinite(pitch))
    unpitched = K - len(known)
    if len(known):
        pitch = np.interp(np.asarray(onsets), np.asarray(onsets)[known], pitch[known])
    else:
        allv = midi[np.isfinite(midi)]
        pitch[:] = float(np.median(allv)) if len(allv) else 50.0
    ns = [Note(a, e, float(p), k) for k, ((a, e), p) in enumerate(zip(spans, pitch))]
    return Result(tidy(ns), list(onsets), 0, doubtful, unpitched)


def place(words, em: tuple, fr: Frames, tuning: np.ndarray, env: np.ndarray | None, gate_db: float, voice_only: bool,
          o: Opts = Opts()) -> Result:
    """The whole rap path: alignment -> sharper onsets -> one note per syllable."""
    lp, frame, vocab, blank = em
    voice = presence(fr, gate_db, voice_only)
    raw = ctc_onsets(words, lp, frame, vocab, blank, fr, voice)
    onsets, moved = refine(raw, env, o)
    clear = (fr.clear if fr.clear is not None else fr.voiced) > 0.3
    midi = np.where(clear, fr.midi - tuning, np.nan)
    r = notes_for(onsets, fr, voice, midi, o)
    r.moved = moved
    return r
