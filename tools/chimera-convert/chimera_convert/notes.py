"""Pitch contour + syllable timings -> notes.

Chimera puts a note's vowel on the beat and sings its onset consonants just before it, so a note
here starts where its syllable's vowel starts. Inside a syllable, the pitch is split into steady
runs: the first carries the syllable, the rest are melisma notes (the vowel held onto a new
pitch). Short gaps between notes are closed (legato); longer ones become rests, which Chimera
uses as breaths and phrase breaks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audio import HOP_S


@dataclass
class Note:
    start: float
    end: float
    midi: float
    syl: int | None
    """global syllable index; None: a melisma note continuing the previous syllable's vowel"""


@dataclass
class Opts:
    min_note: float = 0.10
    """a pitch held shorter than this (s) merges into its neighbour (glides, vibrato flips)"""
    rest: float = 0.25
    """a silence at least this long (s) between notes becomes a rest"""
    bridge: float = 0.06
    """unvoiced gaps shorter than this (s) inside a note are ignored (consonants, tracker drop-outs)"""
    anticipation: float = 0.25
    """a syllable's last pitch shorter than this (s), within 1.5 semitones of the next syllable's,
    is the voice moving to the next note on its onset consonant, not a melisma"""


def smooth(midi: np.ndarray, k: int = 5) -> np.ndarray:
    """NaN-aware running median (keeps the unvoiced frames unvoiced)."""
    out = midi.copy()
    h = k // 2
    for i in np.flatnonzero(~np.isnan(midi)):
        w = midi[max(0, i - h): i + h + 1]
        out[i] = np.nanmedian(w)
    return out


def voiced_segments(t: np.ndarray, m: np.ndarray, a: float, b: float, bridge: float) -> list[tuple[float, float]]:
    idx = np.flatnonzero((t >= a) & (t < b) & ~np.isnan(m))
    if len(idx) == 0:
        return []
    segs = []
    s = p = idx[0]
    for i in idx[1:]:
        if (i - p) * HOP_S > bridge + 1e-9:
            segs.append((t[s], t[p] + HOP_S))
            s = i
        p = i
    segs.append((t[s], t[p] + HOP_S))
    return segs


def pitch_runs(t: np.ndarray, m: np.ndarray, a: float, b: float, o: Opts) -> list[list]:
    """Steady-pitch runs in [a, b): [start, end, values]."""
    idx = np.flatnonzero((t >= a) & (t < b) & ~np.isnan(m))
    if len(idx) == 0:
        return []
    r = np.round(m[idx])
    runs = [[t[idx[0]], t[idx[0]] + HOP_S, [m[idx[0]]]]]
    for j in range(1, len(idx)):
        gap = (idx[j] - idx[j - 1]) * HOP_S > o.bridge + 1e-9
        if r[j] != r[j - 1] or gap:
            runs.append([t[idx[j]], t[idx[j]] + HOP_S, [m[idx[j]]]])
        else:
            runs[-1][1] = t[idx[j]] + HOP_S
            runs[-1][2].append(m[idx[j]])

    def med(run):
        return float(np.median(run[2]))

    # merge the shortest runs into the neighbour closest in pitch
    while len(runs) > 1:
        durs = [x[1] - x[0] for x in runs]
        i = int(np.argmin(durs))
        if durs[i] >= o.min_note:
            break
        cands = [j for j in (i - 1, i + 1) if 0 <= j < len(runs)]
        j = min(cands, key=lambda j: abs(med(runs[j]) - med(runs[i])))
        lo, hi = min(i, j), max(i, j)
        runs[lo] = [runs[lo][0], runs[hi][1], runs[lo][2] + runs[hi][2]]
        del runs[hi]
    # neighbours that now round to the same note are one note
    out = [runs[0]]
    for x in runs[1:]:
        if round(med(x)) == round(med(out[-1])):
            out[-1] = [out[-1][0], x[1], out[-1][2] + x[2]]
        else:
            out.append(x)
    return [[x[0], x[1], med(x)] for x in out]


def nearest_pitch(t: np.ndarray, m: np.ndarray, at: float, default: float = 60.0) -> float:
    v = np.flatnonzero(~np.isnan(m))
    if len(v) == 0:
        return default
    return float(m[v[np.argmin(np.abs(t[v] - at))]])


def sound_end(t, m, a: float, b: float, o: Opts) -> float:
    """Where the syllable stops sounding: the end of its voicing before the first long silence."""
    end = a
    for s, e in voiced_segments(t, m, a, b, o.bridge):
        if s - end > o.rest and end > a:
            break
        end = e
    return end


def from_syllables(onsets: list[float], t: np.ndarray, m: np.ndarray, o: Opts) -> list[Note]:
    """Notes from each syllable's vowel onset (from the alignment)."""
    on = list(np.maximum.accumulate(np.asarray(onsets, float)))
    for k in range(1, len(on)):
        on[k] = max(on[k], on[k - 1] + 0.05)  # two syllables can't share a beat
    voiced = np.flatnonzero(~np.isnan(m))
    t_last = t[voiced[-1]] + HOP_S if len(voiced) else on[-1] + 0.5
    spans, all_runs = [], []
    for k, a in enumerate(on):
        b = on[k + 1] if k + 1 < len(on) else max(t_last, a + 0.3)
        # the voiced run's last frame can reach a frame (10 ms) past the next onset
        end = min(sound_end(t, m, a, b, o), b)
        if end <= a + 0.04:
            end = min(b, a + 0.25)
        spans.append((a, end))
        all_runs.append(pitch_runs(t, m, a, end, o))
    # singers (and Chimera) move to the next note's pitch on its onset consonant, before the
    # vowel: a short last run heading for the next syllable's pitch belongs to the note before it
    for k in range(len(all_runs) - 1):
        runs, nxt = all_runs[k], all_runs[k + 1]
        while len(runs) > 1 and nxt and runs[-1][1] - runs[-1][0] < o.anticipation and abs(runs[-1][2] - nxt[0][2]) <= 1.5:
            runs[-2][1] = runs[-1][1]
            runs.pop()
    notes: list[Note] = []
    for k, ((a, end), runs) in enumerate(zip(spans, all_runs)):
        if not runs:
            notes.append(Note(a, end, nearest_pitch(t, m, a), k))
            continue
        runs[0][0] = a
        runs[-1][1] = end
        for i in range(len(runs) - 1):  # legato inside a syllable
            runs[i][1] = runs[i + 1][0]
        for i, (s_, e, p) in enumerate(runs):
            notes.append(Note(s_, e, p, k if i == 0 else None))
    return notes


def sequential(n_syl: int, t: np.ndarray, m: np.ndarray, o: Opts) -> list[Note]:
    """Without an alignment: notes from the melody alone, then syllables in order. Extra notes
    become melismas (preferring short notes inside a legato line), missing ones are split."""
    notes: list[Note] = []
    group: list[int] = []
    segs = [s for s in voiced_segments(t, m, 0.0, float(t[-1]) + 1, o.bridge) if s[1] - s[0] >= 0.06]
    for g, (a, b) in enumerate(segs):
        runs = pitch_runs(t, m, a, b, o)
        for i in range(len(runs) - 1):
            runs[i][1] = runs[i + 1][0]
        for s, e, p in runs:
            notes.append(Note(s, e, p, 0))
            group.append(g)
    first = [i == 0 or group[i] != group[i - 1] for i in range(len(notes))]
    while len(notes) < n_syl and notes:  # split the longest
        i = max(range(len(notes)), key=lambda i: notes[i].end - notes[i].start)
        n = notes[i]
        mid = (n.start + n.end) / 2
        notes[i:i + 1] = [Note(n.start, mid, n.midi, 0), Note(mid, n.end, n.midi, 0)]
        group[i:i + 1] = [group[i], group[i]]
        first[i:i + 1] = [first[i], False]
    extra = len(notes) - n_syl
    if extra > 0:
        cands = sorted((i for i in range(len(notes)) if not first[i]), key=lambda i: notes[i].end - notes[i].start)
        for i in cands[:extra]:
            notes[i].syl = None
        extra -= min(extra, len(cands))
        while extra > 0:  # still too many: merge the shortest notes into the previous
            i = min((i for i in range(1, len(notes)) if notes[i].syl is not None), key=lambda i: notes[i].end - notes[i].start)
            notes[i - 1].end = notes[i].end
            del notes[i]
            extra -= 1
    k = 0
    for n in notes:
        if n.syl is not None:
            n.syl = k
            k += 1
    return notes
