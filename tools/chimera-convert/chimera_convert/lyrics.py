"""Lyrics -> words -> syllables, the way Chimera will split them.

Chimera sings one syllable per note, so the converter must split the lyrics exactly as Chimera
does, or `render notes` refuses the file ("N syllables for M notes").

- English: Chimera's own split (asked from the Chimera CLI, see chimera.py) when it is found;
  otherwise the same CMU dictionary it uses, with a vowel-group guess for unknown words.
- Finnish: the standard spelling rules (a consonant before a vowel starts a syllable; two vowels
  that are not a long vowel or a diphthong split). Compounds are not detected; hyphenate them in
  the lyrics yourself ("kesä-yö"). The output writes every Finnish word hyphenated, so the count
  does not depend on how Chimera's future Finnish support splits words.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from pathlib import Path

PUNCT = set(".,;:!?\n")


@dataclass
class Syl:
    text: str
    """spelling shown on the note ("twin"), or "~" when the spelling can't be split"""
    span: tuple[int, int] | None = None
    """letters of the word (indices into Word.text) this syllable covers"""
    nucleus: tuple[int, int] | None = None
    """its vowel letters (where the vowel's onset is timed from)"""


@dataclass
class Word:
    text: str
    syls: list[Syl] = field(default_factory=list)
    phrase_end: bool = False
    """a breath follows (comma, full stop, line break)"""


@dataclass
class Token:
    kind: str  # "word" | "punct"
    text: str
    word: int = -1  # index into the word list for kind == "word"


# ----------------------------------------------------------------------------- tokens

def _is_word_char(c: str, lang: str) -> bool:
    if c == "'":
        return True
    if lang == "en":
        return c.isascii() and c.isalpha()  # Chimera's tokenizer: [A-Za-z']
    return c.isalpha()


def tokenize(text: str, lang: str) -> tuple[list[Token], list[Word]]:
    """Words and phrase punctuation, as Chimera's `lyric_tokens` (melisma marks typed in the
    lyrics are dropped: the converter places its own from the melody)."""
    s = text.replace("’", "'").replace("\r\n", "\n").replace("\r", "\n")
    tokens: list[Token] = []
    words: list[Word] = []
    i = 0
    while i < len(s):
        c = s[i]
        if _is_word_char(c, lang):
            j = i + 1
            while j < len(s) and (_is_word_char(s[j], lang) or s[j] == "-"):
                j += 1
            w = s[i:j].rstrip("-")
            if any(ch.isalpha() for ch in w):
                tokens.append(Token("word", w, len(words)))
                words.append(Word(w))
            i = j
            continue
        if c in PUNCT:
            tokens.append(Token("punct", c))
            if words:
                words[-1].phrase_end = True
        i += 1
    return tokens, words


# ----------------------------------------------------------------------------- Finnish

FI_VOWELS = set("aeiouyäöå")
FI_DIPH = {"ai", "ei", "oi", "ui", "yi", "äi", "öi", "au", "eu", "iu", "ou", "ey", "iy", "äy", "öy"}
FI_DIPH_FIRST = {"ie", "uo", "yö"}  # diphthongs only in a word's first syllable


def _fi_part(part: str, offset: int) -> list[Syl]:
    """Syllables of one hyphen-free part; spans index the whole word (offset)."""
    letters = [(k, ch) for k, ch in enumerate(part.lower()) if ch.isalpha()]
    if not letters:
        return []
    is_v = [ch in FI_VOWELS for _, ch in letters]
    if not any(is_v):
        return []
    starts = [0]
    nuc_len = 0  # vowels in the current syllable's nucleus so far
    first_syllable = True
    for n in range(len(letters)):
        k, ch = letters[n]
        if is_v[n]:
            if n > 0 and is_v[n - 1] and starts[-1] != n:
                pair = letters[n - 1][1] + ch
                joins = nuc_len < 2 and (
                    letters[n - 1][1] == ch or pair in FI_DIPH or (first_syllable and pair in FI_DIPH_FIRST)
                )
                if not joins:
                    starts.append(n)
                    first_syllable, nuc_len = False, 0
            nuc_len += 1
        elif n + 1 < len(letters) and is_v[n + 1] and any(is_v[starts[-1]:n]) and starts[-1] != n:
            # a consonant before a vowel starts a new syllable (if the current one has its vowel)
            starts.append(n)
            first_syllable, nuc_len = False, 0
    out: list[Syl] = []
    for si, st in enumerate(starts):
        en = starts[si + 1] if si + 1 < len(starts) else len(letters)
        a, b = letters[st][0], letters[en - 1][0] + 1
        vs = [m for m in range(st, en) if is_v[m]]
        nuc = (letters[vs[0]][0] + offset, letters[vs[-1]][0] + 1 + offset) if vs else None
        text = "".join(part[letters[m][0]] for m in range(st, en))  # original case
        out.append(Syl(text, (a + offset, b + offset), nuc))
    return out


def syllabify_fi(word: str) -> list[Syl]:
    """Typed hyphens and apostrophes ("vaa'an") are syllable breaks."""
    out: list[Syl] = []
    for m in re.finditer(r"[^-']+", word):
        out.extend(_fi_part(m.group(), m.start()))
    return out


# ----------------------------------------------------------------------------- English (fallback)

EN_SPELL_VOWELS = set("aeiouy")


def split_spelling(word: str, n: int) -> list[str]:
    """Port of Chimera's `split_spelling`: a written word in n chunks at its vowel groups."""
    if n <= 1:
        return [word]
    low = word.lower()
    groups = [[m.start(), m.end()] for m in re.finditer(r"[aeiouy]+", low)]
    ln = len(word)
    silent_e = ln >= 2 and low[-1] == "e" and low[-2] not in EN_SPELL_VOWELS
    le = ln >= 3 and low[-1] == "e" and low[-2] == "l" and low[-3] not in EN_SPELL_VOWELS and low[-3] != "l"
    if len(groups) > 1 and silent_e and not le and groups[-1][0] + 1 == ln:
        groups.pop()
    if len(groups) < n:
        return [word] + ["~"] * (n - 1)
    while len(groups) > n:
        last = groups.pop()
        groups[-1][1] = last[1]
    cuts = [0]
    for i in range(len(groups) - 1):
        a, b = groups[i][1], groups[i + 1][0]
        gap = b - a
        dig = gap >= 2 and low[b - 2:b] in ("th", "sh", "ch", "ph", "wh", "ck", "gh")
        cuts.append(b - 2 if dig else a + (0 if gap <= 1 else gap // 2))
    cuts.append(ln)
    return [word[cuts[i]:cuts[i + 1]] for i in range(len(cuts) - 1)]


class CmuDict:
    def __init__(self, path: Path):
        self.d: dict[str, str] = {}
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                tab = line.find("\t")
                if tab > 0:
                    self.d[line[:tab]] = line[tab + 1:]

    def vowels(self, w: str) -> int:
        """Sung syllables in a word, as Chimera's G2P would give them (approximate for unknown
        words: Chimera's letter-to-sound rules are not ported, so vowel groups are counted)."""
        clean = w.lower().strip("'")
        e = self.d.get(clean)
        if e:
            return sum(1 for ph in e.split() if ph[-1:] in "012")
        if "-" in clean:
            return sum(self.vowels(p) for p in clean.split("-") if p)
        low = clean
        groups = re.findall(r"[aeiouy]+", low)
        n = len(groups)
        if n > 1 and len(low) >= 2 and low.endswith("e") and low[-2] not in EN_SPELL_VOWELS and not re.search(r"[^aeiouyl]le$", low):
            n -= 1
        return max(n, 1 if groups else 0)


def en_texts_fallback(word: str, cmu: CmuDict) -> list[str]:
    """Syllable texts of one word, mirroring `lyrics_to_syllables` (typed hyphens split parts)."""
    parts = [p for p in word.split("-") if p]
    out: list[str] = []
    for p in parts:
        n = cmu.vowels(p)
        if len(parts) > 1:
            out += ([p] + ["~"] * (n - 1)) if n else []
        else:
            out += split_spelling(p, n) if n else []
    return out


def attach_spans(word: Word, texts: list[str]) -> None:
    """Syllables from their spelling chunks: spans where the chunks spell the word out."""
    word.syls = []
    pos = 0
    low = word.text.lower()
    for t in texts:
        if t == "~":
            word.syls.append(Syl("~"))
            continue
        # skip hyphens between parts
        while pos < len(low) and low[pos] == "-":
            pos += 1
        if low.startswith(t.lower(), pos):
            a, b = pos, pos + len(t)
            m = re.search(r"[aeiouy]+", low[a:b])
            nuc = (a + m.start(), a + m.end()) if m else (a, b)
            word.syls.append(Syl(t, (a, b), nuc))
            pos = b
        else:
            word.syls.append(Syl(t))


def syllabify(words: list[Word], lang: str, en_texts: list[list[str]] | None = None, cmu: CmuDict | None = None) -> None:
    for i, w in enumerate(words):
        if lang == "fi":
            w.syls = syllabify_fi(w.text)
        else:
            texts = en_texts[i] if en_texts is not None else en_texts_fallback(w.text, cmu)
            attach_spans(w, texts)
