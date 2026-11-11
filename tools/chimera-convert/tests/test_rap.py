"""The rap style: words first, sharper onsets on the vowels, one note per syllable."""

import numpy as np
import pytest

from chimera_convert import audio, pipeline, rap, transcribe
from chimera_convert.transcribe import HOP

SR = 16000
TEXT = "takasi pukemi tavoti sanoka"  # 12 CV syllables


def rap_voice(n_syl=12, rate=9.0, t0=0.4, gap_after=None, whisper=None, seed=0):
    """A fast flow: per syllable a 30 ms noise burst (the consonant, above 2.5 kHz: no energy in
    the vowel band) then a voiced vowel gliding like speech (+1.5 semitones up then down).
    Returns the audio, the true vowel onsets and each syllable's true median pitch over its
    first 70 %."""
    rng = np.random.default_rng(seed)
    syl = 1.0 / rate
    cons = 0.03
    onsets, pitches = [], []
    t = t0
    base = [50, 52, 50, 48, 50, 53, 51, 50, 48, 50, 52, 49]
    dur = t0 + n_syl * syl + 0.6 + (0.4 if gap_after is not None else 0)
    y = np.zeros(int(dur * SR))
    for k in range(n_syl):
        a = int(t * SR)
        nb = int(cons * SR)
        burst = rng.normal(0, 1, nb + 64)
        burst = np.diff(np.diff(burst))[: nb]  # high-passed noise
        y[a:a + nb] += 0.08 * burst
        v0 = t + cons
        onsets.append(v0)
        vl = syl - cons
        n = int(vl * SR)
        tt = np.arange(n) / SR
        glide = 1.5 * np.sin(np.pi * tt / vl)  # up and back down inside the syllable
        midi = base[k % len(base)] + glide
        f = 440 * 2 ** ((midi - 69) / 12)
        ph = 2 * np.pi * np.cumsum(f) / SR
        env = np.minimum(1, np.minimum(tt / 0.008, (vl - tt) / 0.01))
        if whisper is not None and k == whisper:
            v = 0.05 * rng.normal(0, 1, n) * env  # no pitch at all
        else:
            v = sum(np.sin(h * ph) / h for h in range(1, 10)) * env * 0.3
        y[int(v0 * SR):int(v0 * SR) + n] += v[: len(y) - int(v0 * SR)]
        pitches.append(float(np.median(midi[: int(0.7 * n)])))
        t += syl
        if gap_after is not None and k == gap_after:
            t += 0.4
    return y.astype(np.float32), onsets, pitches


def fake_emissions(words, true_onsets, dur, err, frame=0.02):
    """CTC log-probabilities that put each syllable's consonant 40 ms before its vowel and the
    vowel at its true onset + `err[k]` (seconds; the model's boundary drift)."""
    vocab = {"<blank>": 0}
    for w in words:
        for c in w.text:
            vocab.setdefault(c, len(vocab))
    T = int(np.ceil(dur / frame))
    lp = np.full((T, len(vocab)), -8.0)
    lp[:, 0] = 0.0
    k = 0
    for w in words:
        for s in w.syls:
            v = true_onsets[k] + err[k]
            c0, v0 = s.span[0], s.nucleus[0]
            fv = int(round(v / frame))
            fc = max(0, fv - 2)
            lp[fc, vocab[w.text[c0]]] = 0.0
            lp[fc, 0] = -8.0
            lp[fv:fv + 2, vocab[w.text[v0]]] = 0.0
            lp[fv:fv + 2, 0] = -8.0
            k += 1
    lp = lp - np.log(np.exp(lp).sum(1, keepdims=True))
    return lp, frame, vocab, 0


def analyse(y):
    hz, per, rms = audio.raw_pitch(y, "pyin", "cpu")
    an = pipeline.Analysis(y, np.zeros(0), np.zeros(0), "pyin", hz=hz, per=per, rms=rms, voice_only=True,
                           duration=len(y) / SR, env=rap.vowel_envelope(y))
    return pipeline.retranscribe(an)


@pytest.fixture(scope="module")
def flow():
    y, onsets, pitches = rap_voice()
    lyr = pipeline.prepare_lyrics(TEXT, "fi")
    assert len(lyr.syl_word) == len(onsets)
    rng = np.random.default_rng(3)
    err = list(rng.choice([-0.04, -0.02, 0.02, 0.04], len(onsets)))  # the model off by 1-2 frames
    an = analyse(y)
    an.em = fake_emissions(lyr.words, onsets, an.duration, err)
    return y, onsets, pitches, lyr, an


def test_fast_flow_gets_one_note_per_syllable_on_its_vowel(flow):
    """Nine syllables a second in one unbroken voiced run: the model's onsets are 20-40 ms off;
    the vowel band's rise brings them back within a frame or two of 5 ms."""
    _, onsets, pitches, lyr, an = flow
    pl = pipeline.place_notes(lyr, an, "mms", "cpu", pipeline.notes.Opts(rest=0.15), style="rap", log=lambda *_: None)
    ns = pl.notes
    assert [n.syl for n in ns] == list(range(len(onsets)))
    assert not pipeline.check_notes(ns, len(onsets))
    errs = np.abs(np.array([n.start for n in ns]) - np.array(onsets))
    assert np.median(errs) <= 0.012 and errs.max() <= 0.025, errs.round(3)
    # each note's pitch is the syllable's own (the glide's median over its vowel), to a third of a semitone
    tune = float(np.median(an.tr.tuning))
    got = np.array([n.midi for n in ns]) + tune
    assert np.abs(got - np.array(pitches)).max() < 0.35, (got - pitches).round(2)
    assert not pl.doubtful
    mel = pipeline.build_melody(ns, lyr, rest=0.15, keep_cents=True, vibrato=0.0)
    assert mel.sounding == len(onsets) and mel.melismas == 0 and mel.rests == 0


def test_the_singing_path_struggles_on_the_same_flow(flow):
    """Why the rap style exists: notes first finds few steady notes in a gliding flow, and the
    syllables' starts drift from the vowels."""
    _, onsets, _, lyr, an = flow
    pl = pipeline.place_notes(lyr, an, "mms", "cpu", pipeline.notes.Opts(), style="sing", log=lambda *_: None)
    heads = [n for n in pl.notes if n.syl is not None]
    sing = np.abs(np.array([n.start for n in heads]) - np.array(onsets))
    rp = pipeline.place_notes(lyr, an, "mms", "cpu", pipeline.notes.Opts(rest=0.15), style="rap", log=lambda *_: None)
    rapd = np.abs(np.array([n.start for n in rp.notes]) - np.array(onsets))
    assert rapd.mean() < sing.mean()


def test_a_breath_is_a_rest_and_a_whispered_syllable_takes_its_neighbours_pitch():
    y, onsets, pitches = rap_voice(gap_after=5, whisper=8, seed=1)
    lyr = pipeline.prepare_lyrics(TEXT, "fi")
    an = analyse(y)
    an.em = fake_emissions(lyr.words, onsets, an.duration, [0.0] * len(onsets))
    pl = pipeline.place_notes(lyr, an, "mms", "cpu", pipeline.notes.Opts(rest=0.15), style="rap", log=lambda *_: None)
    ns = pl.notes
    assert ns[5].end < onsets[6] - 0.25  # the 0.4 s breath stays a rest
    assert ns[4].end == pytest.approx(ns[5].start, abs=1e-6)  # inside the flow: held (legato)
    lo, hi = sorted([ns[7].midi, ns[9].midi])
    assert lo - 0.01 <= ns[8].midi <= hi + 0.01  # interpolated from its neighbours
    mel = pipeline.build_melody(ns, lyr, rest=0.15, keep_cents=True, vibrato=0.0)
    assert mel.rests == 1


def test_refine_snaps_to_a_rise_keeps_order_and_leaves_lone_onsets():
    def at(t):
        return int(round(t / rap.HOP_ENV))

    env = np.full(400, -60.0)  # 2 s at 5 ms: silence, a vowel at 0.50, a consonant dip, a vowel at 0.62
    env[at(0.50):at(0.58)] = -10.0
    env[at(0.58):at(0.62)] = -40.0
    env[at(0.62):at(0.80)] = -10.0
    out, moved = rap.refine([0.53, 0.60, 1.50], env)
    assert out[0] == pytest.approx(0.50, abs=0.011)
    assert out[1] == pytest.approx(0.62, abs=0.011)
    assert out[2] == 1.50  # no rise near: the model's time
    assert moved == 2
    # two onsets that would snap onto the same rise stay in order, apart
    out, _ = rap.refine([0.49, 0.51], env)
    assert out[1] >= out[0] + 0.04 - 1e-9


def test_rap_needs_the_alignment(flow):
    _, _, _, lyr, an = flow
    with pytest.raises(ValueError, match="alignment"):
        pipeline.place_notes(lyr, an, "none", "cpu", pipeline.notes.Opts(), style="rap", log=lambda *_: None)
    from chimera_convert.__main__ import main

    with pytest.raises(SystemExit, match="alignment"):
        main(["x.wav", "x.txt", "--style", "rap", "--align", "none"])
    with pytest.raises(SystemExit, match="--separate"):
        main(["x.wav", "x.txt", "--lead-only"])


def test_the_envelope_survives_the_analysis_cache(flow, tmp_path):
    _, _, _, _, an = flow
    pipeline.save_analysis(tmp_path / "a.npz", an)
    back = pipeline.load_analysis(tmp_path / "a.npz")
    assert np.allclose(back.env, an.env, atol=0.05)


def test_the_vocal_stem_is_picked_by_its_name():
    assert audio.pick_vocals(["s_(Instrumental)_m.wav", "s_(Vocals)_m.wav"]) == "s_(Vocals)_m.wav"
    assert audio.pick_vocals(["s_(vocals)_k.wav", "s_(other)_k.wav"]) == "s_(vocals)_k.wav"
    with pytest.raises(RuntimeError):
        audio.pick_vocals(["s_(No Vocals)_m.wav", "s_(Drums)_m.wav"])


def test_presence_on_a_voice_track_is_loudness_not_pitch():
    fr = transcribe.frames_from(np.zeros(10), np.zeros(10), np.r_[np.full(5, 0.3), np.full(5, 1e-5)])
    v = rap.presence(fr, -38.0, voice_only=True)
    assert (v[:5] == 1).all() and (v[5:] == 0).all()
    assert (rap.presence(fr, -38.0, voice_only=False) == 0).all()  # a mix: only a clear pitch
    assert HOP == 0.01


def test_roformer_and_lead_voice_plumbing(tmp_path, monkeypatch):
    """audio-separator stand-in: each model writes its two stems; the vocal one is read back, and
    --lead-only runs the karaoke model on the vocal stem.

    Like the real one (0.48), it checks for ffmpeg when it starts and stops with WinError 2 when
    there is none: that stopped RoFormer on a second Windows machine. The converter needs no
    ffmpeg: it hands over a WAV and has soundfile write."""
    import logging
    import sys
    import types

    import soundfile as sf

    calls = []

    class Separator:
        def __init__(self, model_file_dir, output_dir, output_format, use_soundfile=False):
            self.out = output_dir
            self.logger = logging.getLogger("stand-in")
            assert use_soundfile, "pydub would need ffmpeg to write"
            self.check_ffmpeg_installed()

        def check_ffmpeg_installed(self):
            raise FileNotFoundError(2, "The system cannot find the file specified")

        def load_model(self, model_filename):
            self.model = model_filename

        def separate(self, path):
            assert path.endswith(".wav"), "without ffmpeg only a WAV can be read"
            y, sr = sf.read(path)
            calls.append((self.model, sr))
            gain = 0.5 if "karaoke" in self.model else 1.0
            sf.write(f"{self.out}/x_(Vocals)_{self.model}.wav", np.asarray(y) * gain, sr)
            sf.write(f"{self.out}/x_(Instrumental)_{self.model}.wav", np.zeros_like(y), sr)
            return [f"x_(Vocals)_{self.model}.wav", f"x_(Instrumental)_{self.model}.wav"]

    pkg = types.ModuleType("audio_separator")
    mod = types.ModuleType("audio_separator.separator")
    mod.Separator = Separator
    monkeypatch.setitem(sys.modules, "audio_separator", pkg)
    monkeypatch.setitem(sys.modules, "audio_separator.separator", mod)
    monkeypatch.setattr(audio, "_models_dir", lambda: tmp_path)
    src = tmp_path / "song.wav"
    t = np.arange(44100) / 44100
    sf.write(src, 0.4 * np.sin(2 * np.pi * 220 * t), 44100)
    stem = tmp_path / "stem.wav"
    y, sr = audio.separate_vocals(src, "cpu", save_to=stem, log=lambda *_: None, method="roformer", lead_only=True)
    assert sr == 44100 and stem.exists()
    assert [m for m, _ in calls] == [audio.ROFORMER_VOCALS, audio.ROFORMER_LEAD]
    assert np.max(np.abs(y)) == pytest.approx(0.2, abs=0.01)  # through the "karaoke" model
    with pytest.raises(ValueError):
        audio.separate_vocals(src, "cpu", method="spleeter")
    # an mp3 goes in as a WAV made here
    mp3 = tmp_path / "song.mp3"
    sf.write(mp3, 0.4 * np.sin(2 * np.pi * 220 * t), 44100, format="MP3")
    y, sr = audio.separate_vocals(mp3, "cpu", log=lambda *_: None, method="roformer")
    assert sr == 44100 and np.max(np.abs(y)) == pytest.approx(0.4, abs=0.02)


def test_a_missing_separator_module_is_named():
    """audio-separator imports audioread without declaring it: the message must name audioread,
    not claim audio-separator itself is missing (it was installed on the test machine)."""
    e = ModuleNotFoundError("No module named 'audioread'", name="audioread")
    assert "audioread" in audio.missing_separator(e) and "is installed" in audio.missing_separator(e)
    e = ModuleNotFoundError("No module named 'audio_separator'", name="audio_separator")
    assert "needs audio-separator" in audio.missing_separator(e)


def test_a_vowel_after_a_consonant_step_is_found_where_it_reaches_the_vowel():
    """On the real song ("on" at 100.9 s in a 3-minute rap) the band rose in two steps, consonant
    then vowel; the steepest point was the consonant's, 15 ms after it the level was still 23 dB
    under the vowel, and the vowel was refused. It is found now, where it comes within 12 dB of
    the vowel."""
    H = rap.HOP_ENV
    env = np.full(200, -45.0)
    t = np.arange(200) * H
    env[(t >= 0.500) & (t < 0.510)] = -27.0   # the consonant's steep step ...
    ramp = (t >= 0.510) & (t < 0.570)
    env[ramp] = np.linspace(-27, -3, ramp.sum())  # ... rising on without a pause into the vowel
    env[t >= 0.570] = -3.0
    env[t >= 0.800] = -45.0
    r = rap.vowel_rises(env, 4.0)
    assert len(r) == 1 and 0.535 <= r[0] <= 0.555, r
    # legato: a shallow dip between two vowels still counts, at its steepest point
    env2 = np.full(200, -4.0)
    env2[(t >= 0.40) & (t < 0.45)] = -14.0
    r2 = rap.vowel_rises(env2, 4.0)
    assert len(r2) == 1 and abs(r2[0] - 0.45) <= 0.011, r2


def test_lead_only_warns_where_a_hook_sung_by_other_voices_is_gone():
    """The karaoke model kept a real rap's verses but only 22 % of its chorus (the hook is
    other voices): the chorus lyrics then piled onto the ad-libs. Now it says where."""
    sr = 16000
    t = np.arange(40 * sr) / sr
    vocals = 0.3 * np.sin(2 * np.pi * 220 * t)                  # 40 s of voice
    lead = vocals.copy()
    lead[(t >= 20) & (t < 30)] *= 0.01                          # the "chorus" gone from the lead
    msgs = audio.lead_losses(vocals, lead, sr)
    assert len(msgs) == 1 and "20-30 s" in msgs[0] and "kept 0 %" in msgs[0]
    assert audio.lead_losses(vocals, vocals, sr) == []


def test_a_word_with_no_syllable_is_reported_not_dropped_silently():
    """In a Finnish song "MC" has no vowel, so it got no syllable and vanished from the melody
    without a word (seen preparing a real rap's lyrics)."""
    from chimera_convert.notes import Note

    lyr = pipeline.prepare_lyrics("true MC sanoo", "fi")
    assert [w.text for w in lyr.words if not w.syls] == ["MC"]
    ns = [Note(0.5 + 0.3 * k, 0.8 + 0.3 * k, 50, k) for k in range(len(lyr.syl_word))]
    mel = pipeline.build_melody(ns, lyr)
    assert any("MC" in w for w in mel.warnings)


def test_rap_settings_are_clipped_and_reach_the_placement(flow):
    o = rap.Opts.from_dict({"rest": 5.0, "window": -1, "min_rise": None, "nucleus": 0.5})
    assert (o.rest, o.window, o.min_rise, o.nucleus) == (1.0, 0.0, 4.0, 0.5)
    assert rap.Opts.from_dict(o.to_dict()) == o
    # window 0: the onsets stay on the model's times (none sharpened)
    _, onsets, _, lyr, an = flow
    logs = []
    pipeline.place_notes(lyr, an, "mms", "cpu", pipeline.notes.Opts(), style="rap", log=logs.append,
                         rap_opts=rap.Opts.from_dict({"window": 0}))
    assert "0 onsets sharpened" in logs[-1]
