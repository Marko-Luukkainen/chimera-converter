"""Syllables onto the transcribed notes.

The alignment model says roughly when each syllable's vowel starts; the note transcription says
where the singing actually is. This puts every syllable on the start of a sung note, choosing
the whole song at once (dynamic programming) to keep the syllables near the model's times while:

- a syllable starts where a note starts (or at a split of a repeated note), never in silence
  unless nothing else fits (a "virtual" note, costly);
- notes between one syllable and the next are that syllable's melisma (cheap), up to a breath;
- singing after a breath that no syllable claims is dropped (backing vocals, ad libs, bleed);
- a line break or punctuation in the lyrics prefers a breath before the next syllable.

`ctc_onsets` first makes the model's times better: the vowels of the lyrics may only be placed
where someone is singing (the pitch tracker's voicing), so the alignment can't wander into an
instrumental break.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .notes import Note
from .transcribe import HOP, Frames, Segment

VOWELS = set("aeiouy")


@dataclass
class Costs:
    sigma: float = 0.16
    """how far (s) a syllable may sit from the model's time before it costs one unit"""
    vowel_lag: float = 0.05
    """a note's pitch starts on its voiced onset consonant, this much before the vowel (s)"""
    soft: float = 0.4
    """starting a syllable at a split of a repeated note"""
    split: float = 0.8
    """starting a syllable inside a note, where only the model says a syllable changes"""
    virtual: float = 6.0
    """a syllable with no sung note of its own"""
    melisma: float = 0.5
    """each extra pitch a syllable holds"""
    drop: float = 1.5
    """per second of singing no syllable claims"""
    phrase: float = 0.4
    """a line break with (bonus) or without (cost) a breath before the next syllable"""
    window: float = 3.0
    """how far (s) from the model's time a syllable's note may be looked for"""
    split_window: float = 1.0
    """... and a split inside a note"""


# ----------------------------------------------------------------------------- the model's times

def voicing_at(fr: Frames, n: int, frame: float) -> np.ndarray:
    """The pitch tracker's voicing resampled onto the alignment model's frames (max, widened by
    one frame each side: a vowel may start at the edge)."""
    idx = np.minimum((np.arange(n) * frame / HOP).astype(int), fr.n - 1)
    step = max(1, int(round(frame / HOP)))
    v = np.array([fr.voiced[i:i + step].max() for i in idx])
    w = v.copy()
    w[1:] = np.maximum(w[1:], v[:-1])
    w[:-1] = np.maximum(w[:-1], v[1:])
    return w


def constrain(lp: np.ndarray, frame: float, vocab: dict, fr: Frames, strength: float = 1.0) -> np.ndarray:
    """Make vowels unlikely where nobody sings (log-probabilities, a copy)."""
    v = voicing_at(fr, lp.shape[0], frame)
    out = lp.astype(np.float32).copy()
    ids = [vocab[c] for c in VOWELS if c in vocab]
    out[:, ids] += strength * np.log(v + 0.02)[:, None]
    return out


def ctc_onsets(words, lp: np.ndarray, frame: float, vocab: dict, blank: int, fr: Frames) -> list[float]:
    from . import align, pipeline

    lp2 = constrain(lp, frame, vocab, fr)
    labels, where = [], []
    for wi, w in enumerate(words):
        for ci, ch in enumerate(w.text):
            r = align.romanize(ch)
            if len(r) == 1 and r in vocab and r != "-":
                labels.append(vocab[r])
                where.append((wi, ci))
    spans = align.ctc_viterbi(lp2, labels, blank)
    times = [dict() for _ in words]
    for (wi, ci), (f0, f1) in zip(where, spans):
        times[wi][ci] = (f0 * frame, (f1 + 1) * frame)
    return pipeline.syllable_onsets(words, times)


# ----------------------------------------------------------------------------- the assignment

@dataclass
class Point:
    t: float
    seg: int
    """the segment this point starts; for a virtual point -k-1, k its syllable"""
    kind: str  # "start" | "soft" | "split" | "virtual"


def assign(segs: list[Segment], onsets: list[float], phrase_end: list[bool], c: Costs = Costs()) -> list[int]:
    """For each syllable, the index into `points(segs, onsets)` it starts at."""
    pts = points(segs, onsets)
    K = len(onsets)
    if K == 0:
        return []
    tvals = np.array([p.t for p in pts])

    @lru_cache(maxsize=None)
    def material(i: int, j: int) -> float:
        """Cost of what lies between syllable starts at points i and j (j = -1: the song's end)."""
        a = pts[i]
        t_end = pts[j].t if j >= 0 else np.inf
        cost = 0.0
        if a.kind == "virtual":
            # a virtual note: whatever is sung before the next syllable goes unclaimed
            for g, s in enumerate(segs):
                if a.t < s.start < t_end:
                    cost += c.drop * min(s.end, t_end) - c.drop * s.start
            return cost
        rested = False
        g = a.seg + 1
        while g < len(segs) and segs[g].start < t_end - 1e-9:
            s = segs[g]
            if s.after_rest:
                rested = True
            if rested:
                cost += c.drop * (min(s.end, t_end) - s.start)
            elif not s.soft:
                cost += c.melisma
            g += 1
        return cost

    def rest_before(j: int) -> float:
        """the silence before point j (s)"""
        p = pts[j]
        prev_end = max((s.end for s in segs if s.end <= p.t + 1e-9), default=-np.inf)
        return p.t - prev_end

    def emit(k: int, j: int) -> float:
        p = pts[j]
        lag = c.vowel_lag if p.kind in ("start", "soft") else 0.0
        z = (p.t + lag - onsets[k]) / c.sigma
        return min(0.5 * z * z, 12.0) + {"start": 0.0, "soft": c.soft, "split": c.split, "virtual": c.virtual}[p.kind]

    cands = []
    kinds = np.array([p.kind for p in pts])
    for k in range(K):
        dist = np.abs(tvals - onsets[k])
        near = ((dist <= c.window) & ((kinds == "start") | (kinds == "soft"))) | ((dist <= c.split_window) & (kinds == "split"))
        idx = list(np.flatnonzero(near))
        own = next(j for j, p in enumerate(pts) if p.kind == "virtual" and p.seg == -k - 1)
        if own not in idx:
            idx.append(own)
        cands.append(sorted(set(idx), key=lambda j: tvals[j]))
    lead = np.zeros(len(pts))
    for j, p in enumerate(pts):
        # singing before the first syllable goes unclaimed
        lead[j] = c.drop * sum(min(s.end, p.t) - s.start for s in segs if s.start < p.t)
    best = {j: emit(0, j) + lead[j] for j in cands[0]}
    back: list[dict] = [dict()]
    for k in range(1, K):
        cur, bk = {}, {}
        for j in cands[k]:
            e = emit(k, j)
            rb = rest_before(j)
            phr = (-c.phrase if rb >= 0.25 else c.phrase) if phrase_end[k - 1] else (0.6 if rb > 1.0 else 0.0)
            top, arg = np.inf, None
            for i, v in best.items():
                if tvals[i] > tvals[j] - 0.05:
                    continue
                total = v + material(i, j) + phr
                if total < top:
                    top, arg = total, i
            if arg is not None:
                cur[j], bk[j] = top + e, arg
        if not cur:  # nothing fits after the previous syllables: fall back on this syllable's own time
            j = cands[k][-1]
            i = min(best, key=best.get)
            cur, bk = {j: best[i] + emit(k, j)}, {j: i}
        best = cur
        back.append(bk)
    j = min(best, key=lambda j: best[j] + material(j, -1))
    out = [j]
    for k in range(K - 1, 0, -1):
        j = back[k][j]
        out.append(j)
    out.reverse()
    assign.points = pts  # for notes_for
    return out


def points(segs: list[Segment], onsets: list[float], edge: float = 0.06, grid: float = 0.08) -> list[Point]:
    """Where a syllable may start: every note's start, a split inside a note at each syllable's
    model time (fast syllables on one pitch: the pitch alone can't show where they change), and
    a virtual point at each model time."""
    pts = [Point(s.start, g, "soft" if s.soft else "start") for g, s in enumerate(segs)]
    starts = np.array([s.start for s in segs])
    for k, t in enumerate(onsets):
        g = int(np.searchsorted(starts, t, side="right")) - 1
        if g >= 0 and segs[g].start + edge < t < segs[g].end - edge:
            pts.append(Point(t, g, "split"))
    # and a grid inside every note, so syllables the model bunched together can spread out
    for g, s in enumerate(segs):
        for t in np.arange(s.start + grid, s.end - edge, grid):
            pts.append(Point(float(t), g, "split"))
    pts += [Point(t, -k - 1, "virtual") for k, t in enumerate(onsets)]
    pts.sort(key=lambda p: (p.t, p.kind == "virtual"))
    return pts


# ----------------------------------------------------------------------------- notes

def notes_for(segs: list[Segment], onsets: list[float], chosen: list[int], pts: list[Point], fr: Frames | None = None,
              rest: float = 0.25) -> list[Note]:
    """The notes the assignment means: each syllable's head note from its point (moved onto the
    vowel when the model's time falls early in the note), then its melisma notes up to a breath."""
    out: list[Note] = []
    K = len(chosen)
    for k, j in enumerate(chosen):
        p = pts[j]
        t_next = pts[chosen[k + 1]].t if k + 1 < K else np.inf
        if p.kind == "virtual":
            pitch = _nearest_pitch(segs, p.t)
            out.append(Note(p.t, min(p.t + 0.3, t_next), pitch, k))
            continue
        g = p.seg
        s = segs[g]
        # on the vowel: the model's time if it falls early in the note (or just before its voiced
        # start: a tracker notices a pitch a little late)
        start = p.t if p.kind == "split" else min(max(onsets[k], s.start - 0.06), s.start + 0.2, s.end - 0.05)
        head = Note(start, min(s.end, t_next), s.midi, k)
        out.append(head)
        g += 1
        while g < len(segs) and segs[g].start < t_next - 1e-9 and not segs[g].after_rest:
            sg = segs[g]
            if sg.soft or sg.midi == out[-1].midi:
                out[-1].end = min(sg.end, t_next)
            else:
                out.append(Note(sg.start, min(sg.end, t_next), sg.midi, None))
            g += 1
    return tidy(out)


MIN_LEN = 0.04


def tidy(ns: list[Note]) -> list[Note]:
    """Strictly ordered notes, none shorter than MIN_LEN, none overlapping: a melisma note squeezed
    out is dropped; a syllable's note squeezed out pushes the notes after it later."""
    out: list[Note] = []
    for n in ns:  # in sung order (a note moved onto its vowel may start before the one before it)
        n = Note(n.start, n.end, n.midi, n.syl)
        if out:
            prev = out[-1]
            if n.start < prev.start + MIN_LEN:
                if n.syl is None:
                    continue  # a melisma with no room of its own
                n.start = prev.start + MIN_LEN
            prev.end = min(prev.end, n.start)
            if prev.end - prev.start < MIN_LEN:
                prev.end = prev.start + MIN_LEN
                n.start = max(n.start, prev.end)
        n.end = max(n.end, n.start + MIN_LEN)
        out.append(n)
    return out


def _nearest_pitch(segs: list[Segment], t: float) -> float:
    if not segs:
        return 60.0
    return min(segs, key=lambda s: 0 if s.start <= t <= s.end else min(abs(s.start - t), abs(s.end - t))).midi


def hold_over_gaps(ns: list[Note], phrase_end: list[bool], hold: float, breath: float = 0.12) -> list[Note]:
    """Each note held up to the next across a gap shorter than `hold`: sung lyrics are legato, and
    a gap that short is a consonant or a moment the tracker lost the voice, not a rest (left in,
    the voice stops and starts on every syllable and words come out short). Before a line break or
    punctuation in the lyrics only a gap shorter than `breath` is closed, so the singer still
    breathes there."""
    out = [Note(n.start, n.end, n.midi, n.syl) for n in ns]
    head = None
    for a, b in zip(out, out[1:]):
        if a.syl is not None:
            head = a.syl
        gap = b.start - a.end
        if gap <= 0:
            continue
        line_end = b.syl is not None and head is not None and head < len(phrase_end) and phrase_end[head]
        if gap < (breath if line_end else hold):
            a.end = b.start
    return out
