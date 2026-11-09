"""Forced alignment: when each letter of the lyrics is sung.

A multilingual CTC model (MMS forced aligner, 1130 languages incl. Finnish and English; letters
romanized: ä -> a, ö -> o) gives per-frame letter probabilities; a CTC Viterbi pass finds the
most likely path through the lyrics' letters in order. Torchaudio's own forced_align was removed
in torchaudio 2.9, so the Viterbi is done here in numpy.
"""

from __future__ import annotations

import unicodedata

import numpy as np

DEFAULT_MODEL = "MahmoudAshraf/mms-300m-1130-forced-aligner"
SR = 16000


def romanize(ch: str) -> str:
    c = ch.lower()
    if c in "äå":
        return "a"
    if c == "ö":
        return "o"
    d = unicodedata.normalize("NFKD", c)
    return "".join(x for x in d if not unicodedata.combining(x))


def emissions(audio16: np.ndarray, model_id: str, device: str, window_s: float = 30.0, context_s: float = 2.0):
    """Log-probabilities (frames x vocab), the frame length (s) and the vocab."""
    import torch
    from transformers import AutoModelForCTC, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_id)
    # fp32 even on the GPU: in fp16 the MMS aligner overflows and every frame comes out NaN
    model = AutoModelForCTC.from_pretrained(model_id).to(device).eval()
    vocab = {k.lower(): v for k, v in tok.get_vocab().items()}
    blank = vocab.get("<blank>", tok.pad_token_id)

    x = audio16.astype(np.float32)
    n = len(x)
    win, ctx = int(window_s * SR), int(context_s * SR)
    stride = 320  # wav2vec2: 20 ms frames
    parts = []
    for s in range(0, n, win):
        a, b = max(0, s - ctx), min(n, s + win + ctx)
        chunk = x[a:b]
        chunk = (chunk - chunk.mean()) / (chunk.std() + 1e-7)  # MMS expects normalized audio
        with torch.inference_mode():
            t = torch.from_numpy(chunk)[None].to(device)
            logits = model(t).logits[0].float()
            lp = torch.log_softmax(logits, dim=-1).cpu().numpy()
        f0 = (s - a) // stride
        f1 = f0 + (min(n, s + win) - s + stride - 1) // stride
        parts.append(lp[f0:min(f1, len(lp))])
    lp = np.concatenate(parts)
    if not np.isfinite(lp).all():
        raise RuntimeError("the alignment model returned NaN/inf (try --device cpu)")
    return lp, n / SR / len(lp), vocab, blank


def ctc_viterbi(lp: np.ndarray, labels: list[int], blank: int) -> np.ndarray:
    """Best CTC path through `labels` in order. Returns, per label, its first and last frame
    ((L, 2) int array)."""
    T = lp.shape[0]
    L = len(labels)
    if L == 0:
        return np.zeros((0, 2), int)
    ext = np.full(2 * L + 1, blank, dtype=np.int64)
    ext[1::2] = labels
    S = len(ext)
    repeats = sum(1 for i in range(1, L) if labels[i] == labels[i - 1])
    if T < L + repeats:
        raise ValueError(f"audio too short for the lyrics: {T} frames for {L} letters")
    NEG = -1e30
    skip_ok = np.zeros(S, bool)
    skip_ok[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])
    alpha = np.full(S, NEG)
    alpha[0] = lp[0, ext[0]]
    alpha[1] = lp[0, ext[1]]
    back = np.zeros((T, S), np.int8)
    for t in range(1, T):
        a1 = np.concatenate(([NEG], alpha[:-1]))
        a2 = np.concatenate(([NEG, NEG], alpha[:-2]))
        a2[~skip_ok] = NEG
        stack = np.stack([alpha, a1, a2])
        choice = stack.argmax(0)
        alpha = stack[choice, np.arange(S)] + lp[t, ext]
        back[t] = choice
    s = S - 1 if alpha[S - 1] >= alpha[S - 2] else S - 2
    spans = np.full((L, 2), -1, int)
    for t in range(T - 1, -1, -1):
        if s % 2 == 1:
            k = s // 2
            spans[k, 0] = t
            if spans[k, 1] < 0:
                spans[k, 1] = t
        s -= int(back[t, s])  # int(): an int8 from `back` would make s int8 and overflow past 127
    return spans


def align_letters(words, audio16: np.ndarray, model_id: str, device: str, log=print):
    """For each word, a dict letter index -> (start s, end s) for the letters the model knows."""
    log(f"alignment: {model_id} on {device}")
    lp, frame, vocab, blank = emissions(audio16, model_id, device)
    labels, where = [], []
    for wi, w in enumerate(words):
        for ci, ch in enumerate(w.text):
            r = romanize(ch)
            if len(r) == 1 and r in vocab and r not in ("-",):
                labels.append(vocab[r])
                where.append((wi, ci))
    spans = ctc_viterbi(lp, labels, blank)
    out = [dict() for _ in words]
    for (wi, ci), (f0, f1) in zip(where, spans):
        out[wi][ci] = (f0 * frame, (f1 + 1) * frame)
    return out
