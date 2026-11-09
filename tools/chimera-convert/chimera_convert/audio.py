"""Audio in: loading, separating the voice from a full mix, and the sung pitch over time."""

from __future__ import annotations

from pathlib import Path

import numpy as np

HOP_S = 0.01  # pitch frames every 10 ms


def load(path: str | Path, sr: int, mono: bool = True) -> np.ndarray:
    import librosa

    y, _ = librosa.load(str(path), sr=sr, mono=mono)
    return y


def separate_vocals(path: str | Path, device: str, save_to: Path | None = None, log=print) -> tuple[np.ndarray, int]:
    """The vocal stem of a full mix (Demucs htdemucs), mono. Audio I/O is done here, not by
    Demucs, because torchaudio 2.9 dropped the save/load Demucs 4.0 relies on."""
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model("htdemucs")
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
    log(f"separating the voice (Demucs htdemucs on {device}) ...")
    with torch.inference_mode():
        out = apply_model(model, ((x - mean) / std)[None], device=device, split=True, overlap=0.25, progress=True)[0]
    vocals = (out[model.sources.index("vocals")] * std + mean).cpu().numpy()
    if save_to is not None:
        import soundfile as sf

        sf.write(str(save_to), vocals.T, sr)
        log(f"vocal stem: {save_to}")
    return vocals.mean(0), sr


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
