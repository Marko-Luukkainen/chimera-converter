"""chimera-convert: a sung recording + its lyrics -> a melody file for `chimera render notes`.

    python -m chimera_convert song.mp3 lyrics.txt -o song.json [--lang fi|en] [--separate] [--style rap|speech]

The language is read from the lyrics unless --lang names it; when the lyrics don't make it clear
(too few words, both languages, or another language) the run stops and asks for --lang.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import chimera, notes, pipeline, transcribe
from .langdetect import NAMES


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="chimera_convert", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, help="recording (wav, mp3, flac, ...)")
    ap.add_argument("lyrics", type=Path, help="lyrics as UTF-8 text; line breaks and punctuation are breaths")
    ap.add_argument("-o", "--out", type=Path, help="output JSON (default: next to the audio, .json)")
    ap.add_argument("--lang", choices=["auto", "fi", "en"], default="auto",
                    help="the lyrics' language (default: read from the lyrics, asks when unsure)")
    ap.add_argument("--separate", action="store_true", help="separate the voice from a full mix first (Demucs)")
    ap.add_argument("--style", choices=["sing", "rap", "speech"], default="sing",
                    help="sing: notes first, syllables on them (default); rap: words first, one note per syllable "
                         "at the pitch inside it (fast flows, speech-like pitch)")
    ap.add_argument("--separator", choices=["htdemucs", "htdemucs_ft", "roformer"], default="htdemucs",
                    help="with --separate: htdemucs (default), htdemucs_ft (cleaner, ~4x slower) or roformer "
                         "(cleanest; scripts\\install_separator.bat)")
    ap.add_argument("--lead-only", action="store_true",
                    help="with --separate: keep the lead voice alone, without backing vocals, doubles and ad-libs "
                         "(RoFormer karaoke; scripts\\install_separator.bat)")
    ap.add_argument("--align", choices=["mms", "none"], default="mms",
                    help="mms: forced alignment of the lyrics (default); none: syllables to notes in order")
    ap.add_argument("--align-model", default=None, help="Hugging Face CTC model for the alignment")
    ap.add_argument("--pitch", choices=["crepe", "pyin"], default=None, help="pitch tracker (default: crepe if installed)")
    ap.add_argument("--chimera", type=Path, default=None,
                    help="Chimera checkout (default: $CHIMERA_REPO or ~/chimera-vocal-synth); its CLI checks the syllables")
    ap.add_argument("--device", default="auto", help="cuda, cpu or auto")
    ap.add_argument("--transpose", type=float, default=0.0, help="semitones (e.g. -12 for a male voice singing a female part)")
    ap.add_argument("--keep-cents", action=argparse.BooleanOptionalAction, default=None,
                    help="keep the sung pitch to the cent instead of the nearest note (default: on for rap, off for sing)")
    ap.add_argument("--vibrato", type=float, default=None, help="vibrato depth in cents written to the file (default: 35, rap 0)")
    ap.add_argument("--min-note", type=float, default=0.10, help="shortest pitch kept as its own note (s)")
    ap.add_argument("--rest", type=float, default=None, help="shortest silence written as a rest (s, default 0.25, rap 0.15)")
    ap.add_argument("--voice-only", action="store_true", help="the recording is a voice alone (implied by --separate)")
    ap.add_argument("--gate", type=float, default=None, help="singing is louder than this, dB below the loudest moment (default: suggested)")
    ap.add_argument("--clarity", type=float, default=None, help="pitch clarity a frame needs to count as singing, 0..1 (default: suggested)")
    ap.add_argument("--rough", type=float, default=None,
                    help="0..1: how much a loud frame without a clear pitch counts as singing (rough voice; voice tracks only)")
    ap.add_argument("--hold", type=float, default=None, help="hold a syllable over gaps in the singing shorter than this (s, default 0.4)")
    ap.add_argument("--rap-window", type=float, default=None,
                    help="rap: how far (ms) a syllable's onset may move onto its vowel's rise (default 80, 0 keeps the model's times)")
    ap.add_argument("--rap-rise", type=float, default=None, help="rap: the rise (dB per 20 ms) that counts as a vowel starting (default 4)")
    ap.add_argument("--rap-nucleus", type=float, default=None,
                    help="rap: the part of a syllable (0.2-1, from its onset) whose pitch is its pitch (default 0.7)")
    ap.add_argument("--speech-pitch", choices=["voice", "speaker"], default="voice",
                    help="speech: the intonation at the voice's own range (default) or at the speaker's pitch")
    ap.add_argument("--expression", type=float, default=1.0, help="speech: pitch intervals scaled (0.5 flatter, 1.5 livelier; default 1)")
    ap.add_argument("--dynamics", type=float, default=1.0, help="speech: loudness differences scaled (0 even, 1 as spoken)")
    ap.add_argument("--voice", choices=["male", "female", "child", "neanderthal"], default=None,
                    help="the voice (default: from the recording's pitch)")
    ap.add_argument("--plot", action="store_true", help="also write a PNG of the pitch, notes and syllables")
    a = ap.parse_args(argv)
    rap = a.style == "rap"
    spoken = a.style == "speech"
    if a.keep_cents is None:
        a.keep_cents = rap
    if a.vibrato is None:
        a.vibrato = 0.0 if rap else 35.0
    if a.rest is None:
        a.rest = 0.15 if rap else 0.25
    if (rap or spoken) and a.align != "mms":
        raise SystemExit(f"--style {a.style} needs the lyrics alignment (--align mms): it places the words first")
    if (a.lead_only or a.separator != "htdemucs") and not a.separate:
        raise SystemExit("--separator and --lead-only choose how the voice is separated: add --separate")

    out = a.out or a.audio.with_suffix(".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    device = pipeline.pick_device(a.device)
    repo = a.chimera or chimera.default_repo()
    cli = chimera.find_cli(repo)

    text = a.lyrics.read_text(encoding="utf-8-sig")
    try:
        lang, det = pipeline.resolve_lang(text, a.lang)
    except ValueError as e:
        det = e.args[1]
        raise SystemExit(f"language: can't tell from the lyrics (most likely {det['guess']}, "
                         f"confidence {det['confidence']}); run again with --lang fi or --lang en")
    if a.lang == "auto":
        print(f"language: {lang} ({NAMES[lang]}), read from the lyrics, confidence {det['confidence']}")
    elif det["lang"] and det["lang"] != lang:
        print(f"note: the lyrics look like {det['lang']}, singing them as {lang} as asked", file=sys.stderr)

    try:
        lyr = pipeline.prepare_lyrics(text, lang, cli, repo)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"syllables: {lyr.source}")
    print(f"lyrics: {len(lyr.words)} words, {len(lyr.syl_word)} syllables")

    def progress(stage: str, frac: float) -> None:
        if frac == 0.0:
            print(f"{stage} ...")

    an = pipeline.analyze_audio(a.audio, a.separate, device, a.pitch, out.with_suffix(".vocals.wav"), progress,
                                voice_only=a.separate or a.voice_only, separator=a.separator, lead_only=a.lead_only)
    for w in an.warnings:
        pipeline.warn(w)
    sug = an.singing
    chosen = transcribe.Detection(sug.gate_db if a.gate is None else a.gate, sug.clarity if a.clarity is None else a.clarity,
                                  sug.rough if a.rough is None else a.rough, sug.hold if a.hold is None else a.hold)
    if chosen != sug:
        pipeline.retranscribe(an, chosen)
    print(f"pitch: {an.pitch_method} ({an.duration:.1f} s of audio); style: {a.style}")
    print("singing: louder than {gate_db} dB, clarity {clarity}, rough {rough}, held over gaps < {hold} s".format(**an.singing.to_dict()))
    o = notes.Opts(min_note=a.min_note, rest=a.rest)
    try:
        from .rap import Opts as RapOpts

        ro = RapOpts.from_dict({"rest": a.rest, "window": None if a.rap_window is None else a.rap_window / 1000,
                                "min_rise": a.rap_rise, "nucleus": a.rap_nucleus}) if rap or spoken else None
        pl = pipeline.place_notes(lyr, an, a.align, device, o, a.align_model, progress, style=a.style, rap_opts=ro)
        ns = pl.notes
        if pl.doubtful:
            pipeline.warn(f"{len(pl.doubtful)} syllables found no singing to sit on (check them): "
                          + " ".join(lyr.syl_text[k] for k in pl.doubtful[:20]) + (" …" if len(pl.doubtful) > 20 else ""))
        if spoken:
            from . import speech

            so = speech.Opts.from_dict({**ro.__dict__, "pitch": a.speech_pitch, "expression": a.expression, "dynamics": a.dynamics})
            c = pipeline.spoken_contours(an)
            body = a.voice or speech.default_body(c)
            sp = speech.build(ns, ns, lyr, c, so, body, a.transpose, a.audio.name, cli=cli)
            for w in sp.warnings:
                pipeline.warn(w)
            chimera.write_json(out, sp.data)
            chimera.write_csv(out.with_suffix(".csv"), ns, lyr.syl_text, a.transpose)
            if a.plot:
                from .plot import plot

                plot(out.with_suffix(".png"), an.t, an.midi, ns, lyr.syl_text, a.transpose)
            print(f"wrote {out}: speech, {sp.syllables} syllables, {sp.pauses} pauses, {so.pitch} pitch, voice {body}")
            print(f"render: chimera render spoken {out} {out.with_suffix('')}-chimera {body}")
            return 0
        mel = pipeline.build_melody(ns, lyr, a.rest, a.transpose, a.keep_cents, a.vibrato, a.audio.name, cli=cli,
                                    body=a.voice)
    except ValueError as e:
        raise SystemExit(str(e))
    for w in mel.warnings:
        pipeline.warn(w)

    chimera.write_json(out, mel.data)
    chimera.write_csv(out.with_suffix(".csv"), ns, lyr.syl_text, a.transpose)
    if a.plot:
        from .plot import plot

        plot(out.with_suffix(".png"), an.t, an.midi, ns, lyr.syl_text, a.transpose)
    sung = [e[0] for e in mel.data["notes"] if e[0] > 0]
    print(f"wrote {out}: {mel.sounding} notes, {mel.melismas} melisma, {mel.rests} rests, "
          f"range {chimera.note_name(min(sung))}-{chimera.note_name(max(sung))}")
    print(f"render: chimera render notes {out} {out.with_suffix('')}-chimera {mel.data['body']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
