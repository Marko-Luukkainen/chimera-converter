"""A picture to check a conversion: the sung pitch, the notes and their syllables."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def plot(path: Path, t: np.ndarray, midi: np.ndarray, ns, syl_text: list[str], transpose: float = 0.0) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dur = float(t[-1]) if len(t) else 1.0
    fig, ax = plt.subplots(figsize=(max(10, dur * 0.6), 5))
    ax.plot(t, midi + transpose, lw=0.8, color="0.55", label="sung pitch")
    for n in ns:
        p = round(n.midi + transpose)
        color = "tab:blue" if n.syl is not None else "tab:orange"
        ax.add_patch(plt.Rectangle((n.start, p - 0.4), n.end - n.start, 0.8, color=color, alpha=0.5))
        ax.text(n.start, p + 0.6, syl_text[n.syl] if n.syl is not None else "~", fontsize=7)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("MIDI note")
    ax.set_xlim(0, dur)
    ax.grid(alpha=0.3)
    ax.set_title("blue: syllable notes, orange: melisma")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
