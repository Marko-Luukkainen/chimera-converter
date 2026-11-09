import sys
from pathlib import Path

import pytest

from chimera_convert import chimera
from chimera_convert.lyrics import split_spelling, syllabify, syllabify_fi, tokenize


@pytest.mark.parametrize("word,want", [
    ("kissa", "kis-sa"), ("kala", "ka-la"), ("hauis", "hau-is"), ("ruoan", "ruo-an"),
    ("kaikkien", "kaik-ki-en"), ("tuoli", "tuo-li"), ("kesä-yö", "ke-sä-yö"), ("vaa'an", "vaa-an"),
    ("stressi", "stres-si"), ("Päivä", "Päi-vä"), ("maailma", "maa-il-ma"), ("lauantai", "lau-an-tai"),
    ("ylioppilas", "y-li-op-pi-las"), ("tie", "tie"), ("vaikeaa", "vai-ke-aa"), ("laulaa", "lau-laa"),
    ("korkea", "kor-ke-a"), ("valtion", "val-ti-on"), ("hymyilee", "hy-myi-lee"),
])
def test_finnish_syllables(word, want):
    assert "-".join(s.text for s in syllabify_fi(word)) == want


def test_finnish_nucleus_marks_the_vowels():
    s = syllabify_fi("kissa")
    assert [("kissa"[slice(*x.nucleus)]) for x in s] == ["i", "a"]


@pytest.mark.parametrize("word,n,want", [
    ("twinkle", 2, ["twin", "kle"]), ("wonder", 2, ["won", "der"]), ("father", 2, ["fa", "ther"]),
    ("fire", 2, ["fire", "~"]), ("little", 2, ["lit", "tle"]), ("like", 1, ["like"]),
])
def test_split_spelling_matches_chimera(word, n, want):
    assert split_spelling(word, n) == want


def test_tokens_follow_chimera():
    toks, words = tokenize("Twinkle, twinkle - little café!\nHow", "en")
    assert [t.text for t in toks] == ["Twinkle", ",", "twinkle", "little", "caf", "!", "\n", "How"]
    assert [w.phrase_end for w in words] == [True, False, False, True, False]
    toks, words = tokenize("Pieni tähti — tuikkii", "fi")
    assert [w.text for w in words] == ["Pieni", "tähti", "tuikkii"]


def test_group_by_word_reads_chimeras_list():
    _, words = tokenize("twinkle fire ti-ger hmm star", "en")
    texts = ["twin", "kle", "fire", "~", "ti", "ger", "star"]
    assert chimera.group_by_word(words, texts) == [["twin", "kle"], ["fire", "~"], ["ti", "ger"], [], ["star"]]
    assert chimera.group_by_word(words, texts[:-1]) is None


def test_lyrics_text_hyphenates_finnish_and_places_melismas():
    toks, words = tokenize("Pieni tähti,\ntuikkii taivaalla.", "fi")
    syllabify(words, "fi")
    # melismas per syllable: two on "ti" (word end), one on "la" (word end)
    assert chimera.lyrics_text(toks, words, "fi", {3: 2, 8: 1}) == "Pie-ni täh-ti - - ,\ntuik-kii tai-vaal-la - ."
    # one inside a word ("vaal"): the word is written in parts so Chimera can hold the vowel
    assert chimera.lyrics_text(toks, words, "fi", {7: 1}) == "Pie-ni täh-ti,\ntuik-kii tai-vaal - la."


def test_cli_probe_parses_the_count_error(tmp_path):
    fake = tmp_path / "fake.py"
    fake.write_text("import sys\nsys.stderr.write('3 syllables for 1 notes: twin kle star\\n')\nsys.exit(1)\n")
    (tmp_path / "Cargo.toml").write_text("")
    assert chimera.cli_syllables(([sys.executable, str(fake)], tmp_path), "twinkle star") == ["twin", "kle", "star"]
