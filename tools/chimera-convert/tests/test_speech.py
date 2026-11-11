"""The speech style: the recording's timing, pitch and loudness in Chimera's speech file."""

import numpy as np
import pytest

from chimera_convert import pipeline, speech
from chimera_convert.notes import Note
from chimera_convert.transcribe import HOP

LYRICS = "Hyvää huomenta, mitä kuuluu?"  # 9 syllables


def setup(n=9, t0=0.5, step=0.2, pause_after=4):
    lyr = pipeline.prepare_lyrics(LYRICS, "fi")
    assert len(lyr.syl_word) == n
    starts, t = [], t0
    for k in range(n):
        starts.append(t)
        t += step + (0.5 if k == pause_after else 0.0)
    ns = []
    for k, a in enumerate(starts):
        end = a + step - (0.0 if k != pause_after else 0.0)
        ns.append(Note(a, end, 50.0 + k % 3, k))
    T = int((starts[-1] + 1.0) / HOP)
    t = np.arange(T) * HOP
    hz = 150 * 2 ** ((3 * np.sin(2 * np.pi * t / 1.5)) / 12)  # a woman's speech swinging +-3 semitones
    hz[(t > starts[2] + 0.05) & (t < starts[2] + 0.1)] = np.nan  # an unvoiced consonant
    db = np.full(T, -12.0)
    for k in (0, 5):  # two emphasised syllables
        db[int(starts[k] / HOP): int((starts[k] + 0.12) / HOP)] = -3.0
    return lyr, ns, speech.Contours(hz, db), starts


def test_syllables_pitch_and_level_reach_the_file():
    lyr, ns, c, starts = setup()
    sp = speech.build(ns, ns, lyr, c, speech.Opts(pitch="speaker"), "female")
    d = sp.data
    assert d["kind"] == "spoken" and d["lang"] == "fi" and d["lyrics"] == "Hy-vää huo-men-ta, mi-tä kuu-luu?"
    assert [s[0] for s in d["syllables"]] == pytest.approx(starts)
    assert "offset" not in d  # the speech starts late enough for its consonants
    assert sp.pauses == 1  # the half second after "ta,"
    hz = np.array(d["f0"]["hz"])
    t = np.arange(len(hz)) * HOP
    ok = (hz > 0) & (t < starts[-1] + 0.2)
    want = c.hz[: len(hz)][ok]
    assert np.allclose(hz[ok], want, rtol=0.01)  # the speaker's own pitch, untouched
    assert (hz[(t > starts[2] + 0.06) & (t < starts[2] + 0.09)] == 0).all()  # unvoiced: no pitch, Chimera holds it
    lv = np.array(d["level"]["v"])
    peak = lambda k: lv[int((starts[k] + 0.05) / HOP)]
    assert peak(0) > peak(1) + 0.2 and peak(5) > peak(6) + 0.2  # the emphasised syllables drive harder


def test_the_intonation_moves_to_the_voices_range_and_expression_scales_it():
    lyr, ns, c, starts = setup()
    male = speech.build(ns, ns, lyr, c, speech.Opts(pitch="voice"), "male").data["f0"]["hz"]
    hz = np.array([x for x in male if x > 0])
    assert np.median(hz) == pytest.approx(speech.VOICE_HZ["male"], rel=0.05)
    span = 12 * np.log2(hz.max() / hz.min())
    assert 5.5 < span < 6.5  # the +-3 semitone swing kept
    flat = np.array([x for x in speech.build(ns, ns, lyr, c, speech.Opts(pitch="voice", expression=0.5), "male").data["f0"]["hz"] if x > 0])
    assert 12 * np.log2(flat.max() / flat.min()) == pytest.approx(span / 2, abs=0.2)


def test_an_edited_syllable_carries_its_contour_with_it():
    lyr, ns, c, starts = setup()
    auto = [Note(n.start, n.end, n.midi, n.syl) for n in ns]
    # syllable 6 ("tä") 0.1 s later and two semitones up
    ns[6].start += 0.1
    ns[5].end += 0.1
    ns[6].midi += 2
    d = speech.build(ns, auto, lyr, c, speech.Opts(pitch="speaker"), "female").data
    assert d["syllables"][6][0] == pytest.approx(starts[6] + 0.1)
    hz = np.array(d["f0"]["hz"])
    # its new stretch [start + 0.1, end] is the old [start, end] squeezed: 0.05 s into it is 0.1 s
    # into the old one
    t_new = starts[6] + 0.1 + 0.05
    t_old = starts[6] + 0.05 * (auto[6].end - auto[6].start) / (ns[6].end - ns[6].start)
    i_new, i_old = int(round(t_new / HOP)), int(round(t_old / HOP))
    assert 12 * np.log2(hz[i_new] / c.hz[i_old]) == pytest.approx(2.0, abs=0.35)
    # an untouched syllable keeps its pitch
    i = int(round((starts[2] + 0.02) / HOP))
    assert hz[i] == pytest.approx(c.hz[i], rel=0.01)


def test_early_speech_gets_an_offset_for_its_consonants():
    lyr, ns, c, starts = setup(t0=0.1)
    d = speech.build(ns, ns, lyr, c, speech.Opts(), "female").data
    assert d["offset"] == pytest.approx(0.2) and d["syllables"][0][0] == pytest.approx(0.3)
    assert d["f0"]["t0"] == pytest.approx(0.2)


def test_octave_slips_are_dropped_from_the_contour():
    n = 300
    hz = np.full(n, 120.0)
    hz[100:106] = 60.0  # a creak read an octave down
    c = speech.contours(hz, np.full(n, 0.9), np.full(n, -10.0))
    assert np.isnan(c.hz[101:105]).all() and np.isfinite(c.hz[:95]).all()
    assert speech.default_body(c) == "male"


def test_settings_are_clipped():
    o = speech.Opts.from_dict({"expression": 9, "dynamics": -1, "pitch": "robot", "rest": 0.3})
    assert (o.expression, o.dynamics, o.pitch, o.rest) == (2.0, 0.0, "voice", 0.3)
    assert speech.Opts.from_dict(o.to_dict()) == o


def test_the_speech_file_is_written_and_read_back(tmp_path):
    """write_json assumed notes and failed on a speech file (KeyError: 'notes')."""
    import json

    from chimera_convert import chimera

    lyr, ns, c, _ = setup()
    d = speech.build(ns, ns, lyr, c, speech.Opts(), "male").data
    chimera.write_json(tmp_path / "s.json", d)
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8")) == d
