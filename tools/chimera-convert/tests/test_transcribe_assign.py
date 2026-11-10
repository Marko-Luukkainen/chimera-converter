"""Note transcription (tuning, HMM notes) and putting syllables on the notes."""

import numpy as np

from chimera_convert import assign as asg
from chimera_convert import transcribe as tx
from chimera_convert.transcribe import HOP, Segment


def frames(melody, dur, drift_cents=0.0, vibrato_cents=40.0):
    """Frames for a sung melody [(start, end, midi)], with vibrato and a tuning drift that grows
    linearly over the song."""
    n = int(dur / HOP)
    t = np.arange(n) * HOP
    midi = np.full(n, np.nan)
    for a, b, m in melody:
        sel = (t >= a) & (t < b)
        midi[sel] = m
    midi = midi + drift_cents / 100 * t / dur + vibrato_cents / 100 * np.sin(2 * np.pi * 5.5 * t)
    hz = np.where(np.isnan(midi), 0.0, 440 * 2 ** ((np.nan_to_num(midi) - 69) / 12))
    per = np.where(np.isnan(midi), 0.02, 0.9)
    rms = np.where(np.isnan(midi), 1e-4, 0.3)
    return tx.frames_from(hz, per, rms)


MEL = [(0.5, 1.0, 60), (1.0, 1.5, 62), (1.5, 2.0, 64), (2.0, 3.0, 62), (3.6, 4.0, 67), (4.0, 4.4, 65), (4.4, 5.0, 64)]


def test_notes_through_vibrato():
    tr = tx.transcribe(frames(MEL, 5.5))
    assert [round(s.midi) for s in tr.segments] == [60, 62, 64, 62, 67, 65, 64]
    assert [round(s.start, 1) for s in tr.segments] == [0.5, 1.0, 1.5, 2.0, 3.6, 4.0, 4.4]
    assert tr.segments[4].after_rest and not tr.segments[3].after_rest


def test_a_singer_drifting_flat_stays_on_the_same_notes():
    """70 cents flat by the end: rounding to the nearest semitone flips the late notes down; the
    tuning track follows the singer instead."""
    long = [(0.5 + 2 * i, 2.3 + 2 * i, 60 + (i % 3) * 2) for i in range(12)]
    fr = frames(long, 25.0, drift_cents=-70)
    tr = tx.transcribe(fr)
    assert [round(s.midi) for s in tr.segments] == [60 + (i % 3) * 2 for i in range(12)]
    assert tr.tuning[-100] < -0.5  # it followed the drift
    # what plain rounding would have done to the late notes: some flip a semitone down
    flipped = sum(round(np.nanmedian(fr.midi[int(a / HOP):int(b / HOP)])) != m for a, b, m in long)
    assert flipped >= 3


def test_repeated_note_splits_at_a_consonant_gap():
    mel = [(0.5, 0.9, 60), (0.95, 1.4, 60), (1.4, 2.0, 67)]
    tr = tx.transcribe(frames(mel, 2.5, vibrato_cents=0))
    assert [(round(s.midi), s.soft) for s in tr.segments] == [(60, False), (60, True), (67, False)]


def seg(a, b, m, rest=False, soft=False):
    return Segment(a, b, m, 0.0, rest, soft)


def place(segs, onsets, phrase_end=None):
    ch = asg.assign(segs, onsets, phrase_end or [False] * len(onsets))
    pts = asg.assign.points
    return asg.notes_for(segs, onsets, ch, pts), [pts[j].kind for j in ch]


def test_syllables_land_on_note_starts_despite_rough_times():
    segs = [seg(0.5, 1.0, 60, True), seg(1.0, 1.5, 62), seg(1.5, 2.0, 64), seg(2.0, 3.0, 62)]
    ns, kinds = place(segs, [0.62, 1.15, 1.42, 2.2])
    assert [(n.midi, n.syl) for n in ns] == [(60, 0), (62, 1), (64, 2), (62, 3)]
    assert kinds == ["start"] * 4
    # each note starts on its vowel: the model's time, kept within its note's first 0.2 s
    assert [round(n.start, 2) for n in ns] == [0.62, 1.15, 1.44, 2.2]


def test_an_extra_note_is_a_melisma_and_bleed_after_a_breath_is_dropped():
    # two syllables over three notes; after a breath, singing nobody's lyrics claim (backing vocals)
    segs = [seg(0.5, 1.0, 60, True), seg(1.0, 1.4, 62), seg(1.4, 2.0, 64), seg(3.0, 4.0, 70, True)]
    ns, _ = place(segs, [0.55, 1.45])
    assert [(n.midi, n.syl) for n in ns] == [(60, 0), (62, None), (64, 1)]
    assert ns[-1].end <= 2.0


def test_fast_syllables_on_one_pitch_split_the_note():
    segs = [seg(0.5, 2.0, 64, True)]
    ns, kinds = place(segs, [0.55, 1.0, 1.5])
    assert [n.syl for n in ns] == [0, 1, 2] and all(n.midi == 64 for n in ns)
    assert kinds == ["start", "split", "split"]


def test_a_syllable_with_no_singing_is_virtual_and_reported():
    segs = [seg(0.5, 1.0, 60, True), seg(5.0, 5.5, 62, True)]
    ns, kinds = place(segs, [0.55, 2.8, 5.05])
    assert kinds == ["start", "virtual", "start"]
    assert ns[1].midi in (60, 62) and ns[1].end - ns[1].start <= 0.3 + 1e-9


def test_a_line_break_prefers_the_breath():
    # "...sun. | Nyt": the model puts the next syllable slightly before the breath ends
    segs = [seg(0.5, 1.0, 60, True), seg(1.0, 1.6, 62), seg(2.0, 2.5, 64, True)]
    ns, _ = place(segs, [0.55, 1.05, 1.9], phrase_end=[False, True, False])
    assert ns[-1].start >= 2.0 - 0.06 and ns[-1].midi == 64


def test_tidy_never_leaves_empty_or_overlapping_notes():
    from chimera_convert.notes import Note
    from chimera_convert.pipeline import check_notes

    # a syllable on the very start of the previous one, a melisma inside it, a note ending early
    ns = [Note(1.0, 1.5, 60, 0), Note(1.0, 1.2, 62, 1), Note(1.1, 1.15, 63, None), Note(1.6, 1.55, 64, 2)]
    out = asg.tidy(ns)
    assert [n.syl for n in out] == [0, 1, None, 2]
    assert not check_notes(out, 3)
    # sung order wins over start times: a syllable moved onto an early vowel still comes after
    out = asg.tidy([Note(1.0, 1.5, 60, 0), Note(0.95, 1.4, 62, 1)])
    assert [n.syl for n in out] == [0, 1] and not check_notes(out, 2)


def test_rough_singing_counts_on_a_voice_track():
    """A shouted line: loud, but the tracker finds no clear pitch. Only a clear pitch counts by
    default; with `rough` loudness alone does (on a separated voice there is nothing else loud)."""
    n = 300
    hz = np.full(n, 220.0)
    per = np.where(np.arange(n) < 150, 0.9, 0.05)  # clear, then rough
    rms = np.full(n, 0.3)
    plain = tx.frames_with(hz, per, rms, tx.Detection())
    rough = tx.frames_with(hz, per, rms, tx.Detection(rough=0.6))
    assert (plain.voiced[150:] < 0.3).all() and (rough.voiced[150:] >= 0.3).all()
    assert (rough.clear[150:] == 0).all()  # the tuning still follows only the clear part


def test_suggested_thresholds():
    rng = np.random.default_rng(1)
    # a voice track: bleed around -45 dB, singing around -12 dB
    rms = np.concatenate([10 ** (rng.normal(-45, 2, 4000) / 20), 10 ** (rng.normal(-12, 3, 6000) / 20)])
    d = tx.suggest(rms, voice_only=True)
    assert -42 < d.gate_db < -18 and d.rough > 0
    assert tx.suggest(rms, voice_only=False).rough == 0
    assert tx.Detection.from_dict(d.to_dict()) == tx.Detection(*[round(x, 3) if i else round(x, 1) for i, x in enumerate((d.gate_db, d.clarity, d.rough, d.hold))])


def test_short_gaps_are_held_but_a_line_break_breathes():
    from chimera_convert.notes import Note

    ns = [Note(0.0, 0.3, 60, 0), Note(0.5, 0.8, 62, 1), Note(0.85, 1.0, 64, None), Note(1.3, 1.6, 65, 2), Note(2.5, 3.0, 67, 3)]
    out = asg.hold_over_gaps(ns, [False, True, False, False], hold=0.4)
    assert out[0].end == 0.5  # a consonant gap: held
    assert out[1].end == 0.85  # into its own melisma
    assert out[2].end == 1.0  # syllable 1 ends a line: the singer breathes before syllable 2
    assert out[3].end == 1.6  # a real rest (0.9 s) stays


def test_digital_silence_does_not_drag_the_gate_down():
    """A RoFormer stem zeroes the gaps. With those frames in, Otsu split silence from everything
    and suggested -43 dB on a real rap song: breaths and reverb counted as voice, no rest was
    left. Without them the split is between the quiet room and the voice again."""
    rng = np.random.default_rng(2)
    # the real stem's level histogram (% of 10 ms frames per 5 dB bin), digital silence at -100 dB
    hist = {-100: 3, -40: 1, -35: 2, -30: 3, -25: 5, -20: 8, -15: 10, -10: 40, -5: 22}
    db = np.concatenate([rng.uniform(lo, lo + 5, 100 * pct) for lo, pct in hist.items()])
    rms = np.where(db <= -95, 0.0, 10 ** (db / 20))
    d = tx.suggest(rms, voice_only=True)
    assert -25 < d.gate_db < -12, d.gate_db  # it was -43
