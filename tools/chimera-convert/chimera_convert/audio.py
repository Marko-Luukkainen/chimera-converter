"""Audio in: loading, separating the voice from a full mix, and the sung pitch over time."""

from __future__ import annotations

from pathlib import Path

import numpy as np

HOP_S = 0.01  # pitch frames every 10 ms


def load(path: str | Path, sr: int, mono: bool = True) -> np.ndarray:
    import librosa

    y, _ = librosa.load(str(path), sr=sr, mono=mono)
    return y


SEPARATORS = ("htdemucs", "htdemucs_ft", "roformer")
ROFORMER_VOCALS = "vocals_mel_band_roformer.ckpt"
"""Mel-Band RoFormer vocals (Kimberley Jensen), through the audio-separator package"""
ROFORMER_LEAD = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
"""Mel-Band RoFormer karaoke (aufr33, viperx): the lead voice apart from backing vocals"""


def separate_vocals(path: str | Path, device: str, save_to: Path | None = None, log=print, method: str = "htdemucs",
                    lead_only: bool = False, warn=None) -> tuple[np.ndarray, int]:
    """The vocal stem of a full mix, mono.

    method: "htdemucs" (Demucs, the default), "htdemucs_ft" (Demucs fine-tuned: cleaner vocals,
    about four times slower) or "roformer" (Mel-Band RoFormer, the cleanest; needs
    scripts\\install_separator.bat). lead_only: then the lead voice alone, without
    backing vocals, doubles and ad-libs (a RoFormer karaoke model; needs the same package).
    `warn(message)` hears where the lead voice dropped most of the singing (`lead_losses`)."""
    if method not in SEPARATORS:
        raise ValueError(f"separator must be one of {', '.join(SEPARATORS)}")
    if method == "roformer":
        vocals, sr = _roformer(path, ROFORMER_VOCALS, log)
    else:
        vocals, sr = _demucs(path, device, method, log)
    if lead_only:
        lead, sr2 = _lead(vocals, sr, log)
        for msg in lead_losses(vocals.mean(0), lead.mean(0), sr2 if sr2 == sr else sr):
            (warn or log)(msg)
        vocals, sr = lead, sr2
    if save_to is not None:
        import soundfile as sf

        sf.write(str(save_to), vocals.T, sr)
        log(f"vocal stem: {save_to}")
    return vocals.mean(0), sr


def _demucs(path: str | Path, device: str, name: str, log) -> tuple[np.ndarray, int]:
    """Demucs (htdemucs or htdemucs_ft). Audio I/O is done here, not by Demucs, because
    torchaudio 2.9 dropped the save/load Demucs 4.0 relies on."""
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model(name)
    model.eval()
    sr = model.samplerate
    wav = load(path, sr, mono=False)
    if wav.ndim == 1:
        wav = np.stack([wav, wav])
    if wav.shape[0] > 2:
        wav = wav[:2]
    x = torch.from_numpy(np.ascontiguousarray(wav, dtype=np.float32))
    ref = x.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    log(f"separating the voice (Demucs {name} on {device}) ...")
    with torch.inference_mode():
        out = apply_model(model, ((x - mean) / std)[None], device=device, split=True, overlap=0.25, progress=True)[0]
    return (out[model.sources.index("vocals")] * std + mean).cpu().numpy(), sr


def lead_losses(vocals: np.ndarray, lead: np.ndarray, sr: int, window: float = 10.0, keep: float = 0.5) -> list[str]:
    """Where the lead voice kept less than `keep` of the singing (10 s windows, merged): a hook or
    a choir sung by other voices is gone there, and its lyrics would be placed on what is left.

    On a real rap song the karaoke model kept 98-99 % of the verses but 22 % and 40 % of the two
    choruses (the hook is sung by other voices), and the chorus lyrics piled onto the ad-libs."""
    import librosa

    n = min(len(vocals), len(lead))
    hop = int(sr * HOP_S)
    rv = librosa.feature.rms(y=np.asarray(vocals[:n], np.float32), frame_length=4 * hop, hop_length=hop)[0]
    rl = librosa.feature.rms(y=np.asarray(lead[:n], np.float32), frame_length=4 * hop, hop_length=hop)[0]
    ref = rv.max() + 1e-12
    dv, dl = 20 * np.log10(rv / ref + 1e-12), 20 * np.log10(rl / ref + 1e-12)
    voice = dv > -30
    kept = voice & (dl > dv - 10)
    w = int(window / HOP_S)
    spans: list[list[float]] = []
    for a in range(0, len(voice), w):
        v = voice[a:a + w].sum()
        if v < 0.2 * w:  # too little singing here to judge
            continue
        k = kept[a:a + w].sum() / v
        if k < keep:
            t0, t1 = a * HOP_S, min(len(voice), a + w) * HOP_S
            if spans and abs(spans[-1][1] - t0) < 1e-6:
                spans[-1][1] = t1
                spans[-1][2] = min(spans[-1][2], k)
            else:
                spans.append([t0, t1, k])
    return [f"--lead-only dropped most of the voice at {a:.0f}-{b:.0f} s (kept {k * 100:.0f} %): other voices sing "
            f"there (a hook, a choir). Leave those lines out of the lyrics, or convert without --lead-only."
            for a, b, k in spans]


def _models_dir() -> Path:
    d = Path.home() / ".cache" / "chimera-convert" / "separator-models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pick_vocals(files: list[str]) -> str:
    """The vocal stem among audio-separator's outputs ("<song>_(Vocals)_<model>.wav"; the other
    one is "(Instrumental)", "(Other)" or "(No Vocals)")."""
    import re

    hits = [f for f in files if re.search(r"_\((lead )?vocals\)_", Path(f).name, re.IGNORECASE)]
    if len(hits) != 1:
        raise RuntimeError(f"can't tell the vocal stem among {', '.join(Path(f).name for f in files)}")
    return hits[0]


def missing_separator(e: ImportError) -> str:
    """What to install when audio-separator doesn't import: the package itself, or a module it
    needs but doesn't declare (audioread: librosa 1.0 no longer brings it)."""
    name = (getattr(e, "name", None) or "").split(".")[0]
    if name in ("", "audio_separator"):
        return "the RoFormer separator needs audio-separator: run scripts\\install_separator.bat"
    return (f"audio-separator is installed but needs the module '{name}': run scripts\\install_separator.bat "
            f"(or pip install {name})")


def _roformer(path: str | Path, model: str, log) -> tuple[np.ndarray, int]:
    """One audio-separator model on a file: its vocal stem (2, n) at 44.1 kHz."""
    import tempfile

    try:
        from audio_separator.separator import Separator
    except ImportError as e:
        raise RuntimeError(missing_separator(e)) from e
    with tempfile.TemporaryDirectory() as tmp:
        log(f"separating the voice (RoFormer {model}) ...")
        sep = Separator(model_file_dir=str(_models_dir()), output_dir=tmp, output_format="WAV")
        sep.load_model(model_filename=model)
        files = [str(Path(tmp) / Path(f).name) for f in sep.separate(str(path))]
        wav = load(pick_vocals(files), 44100, mono=False)
    if wav.ndim == 1:
        wav = np.stack([wav, wav])
    return wav[:2], 44100


def _lead(vocals: np.ndarray, sr: int, log) -> tuple[np.ndarray, int]:
    """The lead voice of a vocal stem (2, n), without backing vocals and ad-libs."""
    import tempfile

    import soundfile as sf

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "vocals.wav"
        sf.write(str(src), vocals.T, sr)
        log("keeping the lead voice (RoFormer karaoke) ...")
        return _roformer(src, ROFORMER_LEAD, log)


def pitch(y16: np.ndarray, method: str, device: str, fmin: float = 60.0, fmax: float = 1000.0, gate_db: float = -40.0):
    """Sung pitch every 10 ms as MIDI note numbers (NaN where unvoiced). Returns (times, midi)."""
    import librosa

    sr = 16000
    hop = int(HOP_S * sr)
    if method == "crepe":
        import torch
        import torchcrepe

        audio = torch.from_numpy(y16.astype(np.float32))[None]
        f0, per = torchcrepe.predict(
            audio, sr, hop, fmin, fmax, model="full", decoder=torchcrepe.decode.viterbi,
            return_periodicity=True, batch_size=1024, device=device, pad=True,
        )
        per = torchcrepe.filter.median(per, 3)
        f0 = torchcrepe.threshold.At(0.21)(f0, per)
        hz = f0[0].cpu().numpy().astype(float)
    else:
        hz, _, _ = librosa.pyin(y16, fmin=fmin, fmax=fmax, sr=sr, frame_length=1024, hop_length=hop)
    # quiet frames are not singing (bleed, breath, reverb tails)
    rms = librosa.feature.rms(y=y16, frame_length=640, hop_length=hop, center=True)[0]
    n = min(len(hz), len(rms))
    hz, rms = hz[:n], rms[:n]
    db = 20 * np.log10(rms / (rms.max() + 1e-12) + 1e-12)
    hz = np.where((db < gate_db) | ~(hz > 0), np.nan, hz)
    midi = 69 + 12 * np.log2(hz / 440.0)
    t = np.arange(n) * HOP_S
    return t, midi


def raw_pitch(y16: np.ndarray, method: str, device: str, fmin: float = 50.0, fmax: float = 1100.0):
    """The tracker's raw output every 10 ms: (f0 Hz, periodicity 0..1, rms), for transcribe.py."""
    import librosa

    sr = 16000
    hop = int(HOP_S * sr)
    if method == "crepe":
        import torch
        import torchcrepe

        x = torch.from_numpy(y16.astype(np.float32))[None]
        f0, per = torchcrepe.predict(x, sr, hop, fmin, fmax, model="full", decoder=torchcrepe.decode.viterbi,
                                     return_periodicity=True, batch_size=1024, device=device, pad=True)
        hz, per = f0[0].cpu().numpy().astype(float), per[0].cpu().numpy().astype(float)
    else:
        hz, _, per = librosa.pyin(y16, fmin=fmin, fmax=fmax, sr=sr, frame_length=1024, hop_length=hop)
        hz = np.nan_to_num(hz)
    rms = librosa.feature.rms(y=y16, frame_length=640, hop_length=hop, center=True)[0]
    n = min(len(hz), len(per), len(rms))
    return hz[:n], per[:n], rms[:n]
