"""Notes from a synthetic voice: harmonic tones with vibrato, legato steps and a rest."""

import json

import numpy as np
import pytest
import soundfile as sf

from chimera_convert import audio, notes
from chimera_convert.__main__ import main

SR = 16000
# (start s, end s, midi): "Pie-ni täh-ti" legato, a rest, then "tuik-kii" with a melisma on "kii"
MELODY = [(0.50, 0.90, 60), (0.90, 1.30, 62), (1.30, 1.70, 64), (1.70, 2.30, 62),
          (2.80, 3.20, 67), (3.20, 3.60, 65), (3.60, 4.20, 64)]


def voice(melody=MELODY, dur=4.6):
    t = np.arange(int(dur * SR)) / SR
    f = np.zeros_like(t)
    amp = np.zeros_like(t)
    for a, b, m in melody:
        sel = (t >= a) & (t < b)
        f[sel] = 440 * 2 ** ((m - 69) / 12)
        amp[sel] = 1.0
    # vibrato 5.5 Hz +-30 cents, a little glide at note changes (smoothing), soft edges
    k = int(0.03 * SR)
    f = np.convolve(np.where(f > 0, f, np.nan_to_num(f)), np.ones(k) / k, mode="same")
    amp = np.convolve(amp, np.ones(k) / k, mode="same")
    f = f * 2 ** (0.3 * np.sin(2 * np.pi * 5.5 * t) / 12)
    ph = 2 * np.pi * np.cumsum(f) / SR
    y = sum(np.sin(h * ph) / h for h in range(1, 8)) * amp * 0.3
    return y.astype(np.float32)


@pytest.fixture(scope="module")
def contour():
    t, m = audio.pitch(voice(), "pyin", "cpu")
    return t, notes.smooth(m)


def test_from_syllables_finds_the_melody_and_the_melisma(contour):
    t, m = contour
    onsets = [0.5, 0.9, 1.3, 1.7, 2.8, 3.2]  # "kii" carries 65 then 64
    ns = notes.from_syllables(onsets, t, m, notes.Opts())
    assert [round(n.midi) for n in ns] == [60, 62, 64, 62, 67, 65, 64]
    assert [n.syl for n in ns] == [0, 1, 2, 3, 4, 5, None]
    assert abs(ns[3].end - 2.3) < 0.06  # the phrase ends before the rest
    assert abs(ns[-1].start - 3.6) < 0.06
    assert all(a.end <= b.start + 1e-9 for a, b in zip(ns, ns[1:])), "notes overlap"


def test_onsets_between_frames_never_overlap(contour):
    """An onset a few ms after a frame boundary: the note before stops at it (it used to run on
    to its last voiced frame's end, 10 ms over)."""
    t, m = contour
    ns = notes.from_syllables([0.5, 0.903, 1.304, 1.705, 2.8, 3.201], t, m, notes.Opts())
    assert all(a.end <= b.start + 1e-9 for a, b in zip(ns, ns[1:]))


def test_pitch_moving_before_the_vowel_is_not_a_melisma(contour):
    """The pitch changes on the onset consonant, 0.12 s before the vowel the alignment found."""
    t, m = contour
    onsets = [0.5, 1.02, 1.42, 1.82, 2.8, 3.32]
    ns = notes.from_syllables(onsets, t, m, notes.Opts())
    assert [round(n.midi) for n in ns] == [60, 62, 64, 62, 67, 65, 64]
    assert [n.syl for n in ns] == [0, 1, 2, 3, 4, 5, None]


def test_sequential_without_alignment(contour):
    t, m = contour
    ns = notes.sequential(6, t, m, notes.Opts())
    assert [round(n.midi) for n in ns] == [60, 62, 64, 62, 67, 65, 64]
    assert sum(n.syl is None for n in ns) == 1
    assert all(abs(n.start - a) < 0.08 for n, (a, _, _) in zip(ns, MELODY))


def test_cli_end_to_end_finnish(tmp_path):
    wav, txt, out = tmp_path / "laulu.wav", tmp_path / "sanat.txt", tmp_path / "laulu.json"
    sf.write(wav, voice(), SR)
    txt.write_text("Pieni tähti,\ntuikkii yö\n", encoding="utf-8")
    assert main([str(wav), str(txt), "--align", "none", "--pitch", "pyin", "-o", str(tmp_path / "out" / "laulu.json"), "--plot"]) == 0
    out = tmp_path / "out" / "laulu.json"  # the output folder is created
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["bpm"] == 60 and d["lang"] == "fi"
    assert d["lyrics"] == "Pie-ni täh-ti,\ntuik-kii yö"
    pitches = [n[0] for n in d["notes"]]
    assert pitches == [60, 62, 64, 62, 0, 67, 65, 64]
    rest = d["notes"][4][1]
    assert abs(rest - 0.5) < 0.1
    # durations add up to the recording's timeline
    assert abs(d["t0"] + sum(n[1] for n in d["notes"]) - 4.2) < 0.1
    assert (out.with_suffix(".csv")).exists() and (out.with_suffix(".png")).exists()


def test_mms_path_with_a_stand_in_model(tmp_path, monkeypatch):
    """The alignment path end to end, with the CTC model replaced by emissions built from
    known letter times (consonants 60 ms before each vowel onset)."""
    from chimera_convert import align

    text = "pienitähtituikkiiyö"
    # letter -> start time: syllable onsets at the melody's note starts, consonants just before
    plan = [("p", .44), ("ie", .5), ("n", .84), ("i", .9), ("t", 1.24), ("ä", 1.3), ("ht", 1.62), ("i", 1.7),
            ("t", 2.74), ("ui", 2.8), ("kk", 3.1), ("ii", 3.2), ("yö", 3.6)]
    letters = sorted(set(align.romanize(c) for c in text))
    vocab = {"<blank>": 0, **{c: i + 1 for i, c in enumerate(letters)}}
    frame = 0.02
    T = int(4.6 / frame)
    path = [0] * T
    for chunk, t0 in plan:
        f = int(round(t0 / frame))
        for c in chunk:
            path[f] = vocab[align.romanize(c)]
            f += 2
    lp = np.full((T, len(vocab)), -8.0)
    lp[np.arange(T), path] = 0.0
    monkeypatch.setattr(align, "emissions", lambda *a, **k: (lp, frame, vocab, 0))

    wav, txt, out = tmp_path / "laulu.wav", tmp_path / "sanat.txt", tmp_path / "laulu.json"
    sf.write(wav, voice(), SR)
    txt.write_text("Pieni tähti,\ntuikkii yö\n", encoding="utf-8")
    assert main([str(wav), str(txt), "--lang", "fi", "--pitch", "pyin", "-o", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert [n[0] for n in d["notes"]] == [60, 62, 64, 62, 0, 67, 65, 64]
    assert abs(d["t0"] - 0.5) < 0.03
    assert abs(d["notes"][0][1] - 0.4) < 0.03
