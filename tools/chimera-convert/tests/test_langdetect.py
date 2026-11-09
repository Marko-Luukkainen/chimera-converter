import pytest

from chimera_convert.langdetect import detect

FI = [
    # the whole song: "pim pom pum" twice ends in consonants, a weak English hint, not a mix
    "Jaakko kulta, Jaakko kulta, herää jo, herää jo! Kellojasi soita, kellojasi soita: pim pom pum, pim pom pum.",
    "Jaakko kulta, Jaakko kulta, herää jo, herää jo! Kellojasi soita, kellojasi soita: pim pom pum.",
    "Kun kuu nousee taas, minä olen sinun kanssa\nja yö on pitkä",
    "Mä en tiedä mitä sä haluat, mut mä oon tässä vielä huomenna",
    "Pieni tähti tuikkii taivaalla",
]
EN = [
    "Twinkle twinkle little star, how I wonder what you are.",
    "I can't stop loving you, baby, it's you I need tonight",
    "Breathe in, breathe out, I am made of air. Tongue and lips and throat, singing anywhere.",
    "Hello darkness my old friend",
]


@pytest.mark.parametrize("text", FI)
def test_finnish(text):
    d = detect(text)
    assert d.lang == "fi", d


@pytest.mark.parametrize("text", EN)
def test_english(text):
    d = detect(text)
    assert d.lang == "en", d


@pytest.mark.parametrize("text", [
    "Jag har en dröm, och det är din. Du är min vän för alltid",
    "Ich hab dich lieb, und du bist mein, für immer und ewig",
])
def test_neighbours_with_umlauts_are_not_finnish(text):
    d = detect(text)
    assert d.lang is None and d.guess == "other", d


def test_mixed_lyrics_ask():
    d = detect("Mä oon tässä taas ja sä et tiedä mitään\nI love you baby, don't you know it's true\n"
               "minä odotan sinua kotona\nyou are the one tonight")
    assert d.lang is None and "mix Finnish and English" in d.reason, d


@pytest.mark.parametrize("text", ["", "La la la", "Pim pom", "oo"])
def test_too_little_to_tell_asks(text):
    d = detect(text)
    assert d.lang is None, d


def test_cli_stops_and_asks_when_the_language_is_unclear(tmp_path):
    from chimera_convert.__main__ import main

    (tmp_path / "s.txt").write_text("La la la", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path / "missing.wav"), str(tmp_path / "s.txt"), "-o", str(tmp_path / "o.json")])
    assert "--lang fi or --lang en" in str(e.value)
