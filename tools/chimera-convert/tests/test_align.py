import numpy as np

from chimera_convert.align import ctc_viterbi, romanize


def emissions(path, V=5, sharp=8.0):
    """Log-probs that favour the given token per frame."""
    lp = np.full((len(path), V), -sharp)
    for t, k in enumerate(path):
        lp[t, k] = 0.0
    return lp - np.log(np.exp(lp).sum(1, keepdims=True))


def test_viterbi_finds_letter_spans():
    # blank 0; letters 1 2 3; "a b b" needs a blank between the repeated b's
    path = [0, 0, 1, 1, 1, 0, 2, 2, 0, 0, 2, 2, 2, 0]
    spans = ctc_viterbi(emissions(path), [1, 2, 2], blank=0)
    assert spans.tolist() == [[2, 4], [6, 7], [10, 12]]


def test_viterbi_survives_noise():
    rng = np.random.default_rng(1)
    path = [0] * 5 + [1] * 10 + [0] * 3 + [3] * 10 + [0] * 5
    lp = emissions(path, sharp=3.0) + rng.normal(0, 0.8, (len(path), 5))
    spans = ctc_viterbi(lp, [1, 3], blank=0)
    assert abs(spans[0][0] - 5) <= 1 and abs(spans[1][0] - 18) <= 1


def test_romanize_finnish():
    assert [romanize(c) for c in "äöåÉ"] == ["a", "o", "a", "e"]


def test_viterbi_long_lyrics():
    """More than 64 letters: the state index passes int8's range (an overflow once)."""
    labels = [1 + (i % 3) for i in range(100)]
    path = []
    for i, k in enumerate(labels):
        path += [k, k, 0]
    spans = ctc_viterbi(emissions(path), labels, blank=0)
    assert spans[:, 0].tolist() == [3 * i for i in range(100)]
