"""The conversion as steps that return data, shared by the CLI and the app's server.

    lyr = prepare_lyrics(text, lang, cli, repo)        # words -> syllables (Chimera's split)
    an = analyze_audio(path, separate, device, ...)    # voice -> pitch contour
    ns = place_notes(lyr, an, align, device, opts)     # syllables -> notes
    mel = build_melody(ns, lyr, ...)                   # notes -> the melody file for Chimera

`progress(stage, fraction)` reports where a long step is (the app shows it).
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, chimera, lyrics, notes, transcribe
from .langdetect import detect

Progress = Callable[[str, float], None]


def _quiet(stage: str, frac: float) -> None:
    pass


def pick_device(want: str = "auto") -> str:
    if want != "auto":
        return want
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


# ----------------------------------------------------------------------------- lyrics

@dataclass
class Lyrics:
    lang: str
    tokens: list[lyrics.Token]
    words: list[lyrics.Word]
    source: str = ""
    """where the syllable split came from (shown to the user)"""

    @property
    def syl_word(self) -> list[tuple[int, int]]:
        return [(wi, si) for wi, w in enumerate(self.words) for si in range(len(w.syls))]

    @property
    def syl_text(self) -> list[str]:
        return [self.words[wi].syls[si].text for wi, si in self.syl_word]

    def to_dict(self) -> dict:
        return {"lang": self.lang, "source": self.source, "tokens": [asdict(t) for t in self.tokens],
                "words": [asdict(w) for w in self.words]}

    @staticmethod
    def from_dict(d: dict) -> "Lyrics":
        tokens = [lyrics.Token(**t) for t in d["tokens"]]
        words = []
        for w in d["words"]:
            syls = [lyrics.Syl(s["text"], tuple(s["span"]) if s["span"] else None, tuple(s["nucleus"]) if s["nucleus"] else None) for s in w["syls"]]
            words.append(lyrics.Word(w["text"], syls, w["phrase_end"]))
        return Lyrics(d["lang"], tokens, words, d.get("source", ""))


def resolve_lang(text: str, lang: str) -> tuple[str, dict]:
    """`lang` as given, or the detected one for "auto". Raises ValueError (with the detection
    in its args) when auto can't tell."""
    det = detect(text)
    if lang != "auto":
        return lang, det.to_dict()
    if det.lang is None:
        raise ValueError(det.reason, det.to_dict())
    return det.lang, det.to_dict()


def prepare_lyrics(text: str, lang: str, cli=None, repo: Path | None = None) -> Lyrics:
    tokens, words = lyrics.tokenize(text, lang)
    if not words:
        raise ValueError("no words in the lyrics")
    source = "Finnish spelling rules"
    if lang == "en":
        texts = None
        if cli:
            flat = chimera.cli_syllables(cli, " ".join(w.text for w in words))
            if flat and flat != ["?"]:
                texts = chimera.group_by_word(words, flat)
        if texts is not None:
            source = "Chimera's own split"
            lyrics.syllabify(words, "en", en_texts=texts)
        else:
            cmu_path = repo / "public/data/cmudict.txt.gz" if repo else None
            if not cmu_path or not cmu_path.exists():
                raise ValueError("English needs the Chimera checkout (--chimera PATH) for its dictionary")
            source = "CMU dictionary (Chimera CLI not found; unknown words are guessed)"
            lyrics.syllabify(words, "en", cmu=lyrics.CmuDict(cmu_path))
    else:
        lyrics.syllabify(words, "fi")
    return Lyrics(lang, tokens, words, source)


# ----------------------------------------------------------------------------- audio

@dataclass
class Analysis:
    y16: np.ndarray | None
    """the voice at 16 kHz (None for an analysis read back from its cache)"""
    t: np.ndarray
    midi: np.ndarray
    """sung pitch with the singer's tuning removed (MIDI, NaN unvoiced) every 10 ms"""
    pitch_method: str
    vocals: Path | None = None
    tr: "transcribe.Transcription | None" = None
    """the notes found in the singing, before the lyrics"""
    hz: np.ndarray | None = None
    per: np.ndarray | None = None
    rms: np.ndarray | None = None
    """the tracker's raw output every 10 ms, kept to find the singing again with other thresholds"""
    voice_only: bool = False
    """the audio is a voice alone (separated, or recorded so): loudness alone can mean singing"""
    singing: "transcribe.Detection | None" = None
    """what counted as singing"""
    em: tuple | None = None
    """the alignment model's output (log-probabilities, frame length, vocab, blank), once computed"""
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)
    """what the separation found worth telling (audio.lead_losses)"""
    env: np.ndarray | None = None
    """the vowel band's energy every 5 ms (rap.vowel_envelope), for rap's sharper syllable onsets"""


STYLES = ("sing", "rap")


def retranscribe(an: Analysis, singing: "transcribe.Detection | None" = None) -> Analysis:
    """The notes in the singing, with these thresholds (suggested ones when None)."""
    det = singing or transcribe.suggest(an.rms, an.voice_only)
    fr = transcribe.frames_with(an.hz, an.per, an.rms, det)
    tr = transcribe.transcribe(fr)
    an.tr, an.singing = tr, det
    an.midi = np.where(fr.voiced >= 0.3, fr.midi - tr.tuning, np.nan)
    an.t = np.arange(fr.n) * transcribe.HOP
    return an


def save_analysis(path: Path, an: Analysis) -> None:
    """The raw analysis (and the alignment model's output), so new thresholds or a new language
    don't run the models again."""
    extra = {}
    if an.em is not None:
        lp, frame, vocab, blank = an.em
        extra = {"lp": lp.astype(np.float16), "frame": frame, "vocab": json.dumps(vocab), "blank": blank}
    tmp = path.with_name(path.stem + ".tmp.npz")
    if an.env is not None:
        extra["env"] = an.env.astype(np.float16)
    np.savez_compressed(tmp, hz=an.hz, per=an.per, rms=an.rms, pitch_method=an.pitch_method, voice_only=an.voice_only,
                        duration=an.duration, **extra)
    tmp.replace(path)


def load_analysis(path: Path, singing: "transcribe.Detection | None" = None) -> Analysis:
    d = np.load(path)
    em = None
    if "lp" in d:
        em = (d["lp"].astype(np.float32), float(d["frame"]), json.loads(str(d["vocab"])), int(d["blank"]))
    an = Analysis(None, np.zeros(0), np.zeros(0), str(d["pitch_method"]), hz=d["hz"], per=d["per"], rms=d["rms"],
                  voice_only=bool(d["voice_only"]), em=em, duration=float(d["duration"]),
                  env=d["env"].astype(np.float32) if "env" in d else None)
    return retranscribe(an, singing)


def analyze_audio(path: Path, separate: bool, device: str, pitch_method: str | None = None,
                  vocals_out: Path | None = None, progress: Progress = _quiet,
                  singing: "transcribe.Detection | None" = None, voice_only: bool | None = None,
                  separator: str = "htdemucs", lead_only: bool = False) -> Analysis:
    warnings: list[str] = []
    if separate:
        progress("separating the voice", 0.0)
        voc, sr = audio.separate_vocals(path, device, save_to=vocals_out, log=lambda *_: None, method=separator,
                                        lead_only=lead_only, warn=warnings.append)
        import librosa

        y16 = librosa.resample(voc, orig_sr=sr, target_sr=16000)
    else:
        progress("loading", 0.0)
        y16 = audio.load(path, 16000)
    if pitch_method is None:
        try:
            import torchcrepe  # noqa: F401

            pitch_method = "crepe"
        except ImportError:
            pitch_method = "pyin"
    progress("pitch", 0.0)
    hz, per, rms = audio.raw_pitch(y16, pitch_method, device)
    from .rap import vowel_envelope

    an = Analysis(y16, np.zeros(0), np.zeros(0), pitch_method, vocals_out if separate else None, hz=hz, per=per, rms=rms,
                  voice_only=separate if voice_only is None else voice_only, duration=len(y16) / 16000,
                  warnings=warnings, env=vowel_envelope(y16))
    return retranscribe(an, singing)


# ----------------------------------------------------------------------------- notes

def syllable_onsets(words: list[lyrics.Word], letter_times: list[dict]) -> list[float]:
    """Each syllable's vowel onset from its letters' alignment; syllables the alignment can't
    place (no spelling of their own, or letters the model doesn't know) are interpolated."""
    raw: list[float | None] = []
    for w, times in zip(words, letter_times):
        for s in w.syls:
            t = None
            if s.nucleus:
                ts = [times[c][0] for c in range(*s.nucleus) if c in times]
                t = min(ts) if ts else None
            if t is None and s.span:
                ts = [times[c][0] for c in range(*s.span) if c in times]
                t = max(ts) if ts else None
            raw.append(t)
    known = [i for i, t in enumerate(raw) if t is not None]
    if not known:
        raise ValueError("alignment placed no syllable; check that the lyrics match the recording")
    xs, ys = np.array(known, float), np.array([raw[i] for i in known])
    out = np.interp(np.arange(len(raw)), xs, ys)
    for i in range(known[0] - 1, -1, -1):
        out[i] = out[i + 1] - 0.3
    for i in range(known[-1] + 1, len(raw)):
        out[i] = out[i - 1] + 0.3
    return [max(0.0, float(x)) for x in out]


@dataclass
class Placement:
    notes: list[notes.Note]
    doubtful: list[int] = field(default_factory=list)
    """syllables placed where no singing fits them (worth a look in the editor)"""


def place_notes(lyr: Lyrics, an: Analysis, align_mode: str, device: str, o: notes.Opts,
                align_model: str | None = None, progress: Progress = _quiet, log=print, style: str = "sing",
                rap_opts: "rap.Opts | None" = None) -> Placement:
    """rap_opts: the rap style's settings (defaults, with `o.rest` as the rest, when None)."""
    doubtful: list[int] = []
    if style not in STYLES:
        raise ValueError(f"style must be one of {', '.join(STYLES)}")
    if style == "rap":
        if align_mode != "mms":
            raise ValueError("the rap style needs the lyrics alignment (align: mms): it places the words first")
        from . import align, rap

        progress("aligning the lyrics", 0.0)
        if an.em is None:
            if an.y16 is None:
                raise ValueError("the alignment model's output is missing; analyse the recording again")
            an.em = align.emissions(an.y16, align_model or align.DEFAULT_MODEL, device)
        if an.env is None and an.y16 is not None:
            an.env = rap.vowel_envelope(an.y16)
        if an.env is None:
            log("rap: no vowel band envelope in this analysis (made by an older version): onsets are the model's")
        det = an.singing or transcribe.Detection()
        r = rap.place(lyr.words, an.em, an.tr.frames, an.tr.tuning, an.env, det.gate_db, an.voice_only,
                      rap_opts or rap.Opts(rest=o.rest))
        log(f"rap: {len(r.notes)} syllables, {r.moved} onsets sharpened on the vowels, "
            f"{r.unpitched} with no clear pitch of their own (pitch from their neighbours)")
        if not r.notes:
            raise ValueError("no notes found (is there a voice in the recording?)")
        return Placement(r.notes, r.doubtful)
    if align_mode == "mms":
        from . import align, assign

        progress("aligning the lyrics", 0.0)
        if an.em is None:
            an.em = align.emissions(an.y16, align_model or align.DEFAULT_MODEL, device)
        lp, frame, vocab, blank = an.em
        onsets = assign.ctc_onsets(lyr.words, lp, frame, vocab, blank, an.tr.frames)
        phrase_end = [lyr.words[wi].phrase_end and si == len(lyr.words[wi].syls) - 1 for wi, si in lyr.syl_word]
        segs = an.tr.segments
        chosen = assign.assign(segs, onsets, phrase_end)
        pts = assign.assign.points
        ns = assign.notes_for(segs, onsets, chosen, pts)
        ns = assign.hold_over_gaps(ns, phrase_end, an.singing.hold if an.singing else 0.4)
        heads = {n.syl: n for n in ns if n.syl is not None}
        doubtful = [k for k, j in enumerate(chosen) if pts[j].kind == "virtual" or (k in heads and abs(heads[k].start - onsets[k]) > 0.6)]
    else:
        ns = notes.sequential(len(lyr.syl_word), an.t, an.midi, o)
    if lyr.lang != "fi":  # Finnish words are written in parts around a melisma (chimera.lyrics_text)
        ns = chimera.merge_inner_melismas(ns, lyr.syl_word, lyr.words, log=log)
    if not ns:
        raise ValueError("no notes found (is there singing in the recording?)")
    return Placement(ns, doubtful)


# ----------------------------------------------------------------------------- melody

@dataclass
class Melody:
    data: dict
    """the melody file for `chimera render notes`"""
    warnings: list[str] = field(default_factory=list)
    sounding: int = 0
    melismas: int = 0
    rests: int = 0


def check_notes(ns: list[notes.Note], n_syl: int) -> list[str]:
    """Problems that would make the melody wrong for Chimera."""
    errs = []
    heads = [n.syl for n in ns if n.syl is not None]
    if heads != list(range(n_syl)):
        errs.append(f"syllables on notes must be 0..{n_syl - 1} in order, got {len(heads)} heads")
    if ns and ns[0].syl is None:
        errs.append("the first note must start a syllable")
    for a, b in zip(ns, ns[1:]):
        if b.start < a.end - 1e-6:
            errs.append(f"notes overlap at {b.start:.2f} s")
            break
    if any(n.end <= n.start for n in ns):
        errs.append("a note has no length")
    return errs


def build_melody(ns: list[notes.Note], lyr: Lyrics, rest: float = 0.25, transpose: float = 0.0,
                 keep_cents: bool = False, vibrato: float = 35.0, source: str = "", body: str | None = None,
                 cli=None) -> Melody:
    errs = check_notes(ns, len(lyr.syl_word))
    if errs:
        raise ValueError("; ".join(errs))
    melismas: dict[int, int] = {}
    head = None
    for n in ns:
        if n.syl is None and head is not None:
            melismas[head] = melismas.get(head, 0) + 1
        elif n.syl is not None:
            head = n.syl
    text = chimera.lyrics_text(lyr.tokens, lyr.words, lyr.lang, melismas)
    ev, t0 = chimera.events(ns, rest, transpose, keep_cents)
    sounding = sum(1 for e in ev if e[0] > 0)
    warnings = []
    silent = [w.text for w in lyr.words if not w.syls]
    if silent:
        warnings.append(f"no syllable in {', '.join(dict.fromkeys(silent))}: left out of the song; "
                        "write them as they are said (MC -> äm-sii)")
    expected = len(lyr.syl_word) + sum(melismas.values())
    if sounding != expected:
        warnings.append(f"{sounding} notes for {expected} syllables")
    if cli:
        check = chimera.cli_syllables(cli, text, lyr.lang)
        if check is not None and check != ["?"] and len(check) != sounding:
            warnings.append(f"Chimera reads {len(check)} syllables for {sounding} notes; fix the lyrics (hyphens) or the notes")
    sung = [e[0] for e in ev if e[0] > 0]
    if body is None:
        body = "male" if np.median(sung) < 57 else "female"
    data = {"bpm": 60, "lyrics": text, "t0": max(t0, 0.3), "vibrato": vibrato,
            "source": source, "lang": lyr.lang, "body": body, "notes": ev}
    if t0 < 0.3:
        data["offset"] = round(0.3 - t0, 3)  # the render starts this much later than the recording
    return Melody(data, warnings, sounding, sum(melismas.values()), sum(1 for e in ev if e[0] <= 0))


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)
