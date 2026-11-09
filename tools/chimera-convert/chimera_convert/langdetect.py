"""Which language the lyrics are in: Finnish, English, or neither (then the user is asked).

Chimera sings Finnish and English, so the question is narrow: is this Finnish, English, or
something else? Lyrics are text we already have, so the guess is made from the words: letters
only one language uses (ä ö in Finnish; w, th, apostrophe contractions in English), the commonest
small words, Finnish case endings and double vowels. Swedish, German and Estonian share ä/ö with
Finnish, so their own common words and letters count against both, and a song that looks like
them is reported as "other" instead of being sung with Finnish rules.

The answer is a language only when the evidence is clear; otherwise `lang` is None and the
caller asks (the CLI stops and names --lang, the app shows a language choice).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

FI_WORDS = set("""
ja on ei se että mä sä minä sinä hän me te he mun sun mua sua mulle sulle mut sut kun niin mutta jo
vain ole oli olen olet ollut nyt tämä tää tuo toi siinä siellä täällä kuin jos vaan myös vielä aina
koskaan mitä miksi missä mikä kuka mihin miten kanssa sinun minun meidän teidän heidän ne nää noi
sen sitä siitä tänään huomenna eilen yö päivä kuu aurinko rakkaus sydän hei moi kiitos anna tule
mene pois kotiin taas enää yhä ehkä varmaan kaikki joka jota jonka mikään kukaan yksi kaksi kolme
nyt saa voi pitää täytyy haluan halusin oot oon ois olis olla vaan joo juu niinku vähän paljon
""".split())
EN_WORDS = set("""
the and you i me my to a of in is it that on for be are was were what how with all this so can we know
don't i'm you're it's i'll can't won't your our they them their there here when where why who love
baby oh yeah just like never ever now but not no yes do does did got get go going gonna wanna let
heart night day time way one up down out from at by if or as an will would could should been have has
had into over again still back away tonight feel see say tell come give take make want need
""".split())
# words that are common in a neighbour with ä/ö (or ü/õ/ß), not in Finnish or English
OTHER_WORDS = set("""
och jag det är inte att på med som du mig dig han hon vi ni de för till av men om har var
und ich der die das nicht ist mich dich ein eine zu mit auf für sind wir ihr sie es
ma sa ta oled olen mina sina tema meie teie nemad kui ning aga veel
""".split())
FI_SUFFIX = re.compile(r"(ssa|ssä|sta|stä|lla|llä|lta|ltä|lle|ksi|nsa|nsä|mme|tte|vat|vät|kin|kaan|kään|ko|kö|han|hän|nen|ni|si)$")
FI_DOUBLE = re.compile(r"(aa|ee|ii|oo|uu|yy|ää|öö|kk|pp|tt|ll|mm|nn|ss)")
EN_LETTERS = re.compile(r"(th|wh|w|c|q|x|z|gh|ck|ph|sh)")
EN_CONTRACTION = re.compile(r"'(s|t|m|re|ll|ve|d)$")
EN_END = re.compile(r"[bcdfgkmpvwxz]$")

NAMES = {"fi": "Finnish", "en": "English", "other": "another language"}


@dataclass
class Detection:
    lang: str | None
    """"fi", "en", or None when unsure or the lyrics look like another language"""
    guess: str
    """the most likely of "fi", "en", "other" even when unsure"""
    confidence: float
    """0..1: the winning share of the evidence"""
    reason: str
    """one line for the app"""
    scores: dict = field(default_factory=dict)
    words: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text.lower().replace("’", "'"))


def score_word(w: str) -> dict[str, float]:
    s = {"fi": 0.0, "en": 0.0, "other": 0.0}
    if re.search(r"[äö]", w):
        s["fi"] += 2.0
        s["other"] += 1.0  # Swedish, German, Estonian have them too
    if re.search(r"[åüõß]", w):
        s["other"] += 3.0
    if w in FI_WORDS:
        s["fi"] += 2.0
    if w in EN_WORDS:
        s["en"] += 2.0
    if w in OTHER_WORDS:
        s["other"] += 2.0
    if len(w) > 4 and FI_SUFFIX.search(w):
        s["fi"] += 1.0
    if FI_DOUBLE.search(w):
        s["fi"] += 0.5
    if EN_LETTERS.search(w):
        s["en"] += 1.0
    if EN_CONTRACTION.search(w):
        s["en"] += 2.0
    if EN_END.search(w):
        s["en"] += 0.5
    return s


def detect(text: str, min_confidence: float = 0.65, min_evidence: float = 4.0) -> Detection:
    ws = _words(text)
    total = {"fi": 0.0, "en": 0.0, "other": 0.0}
    per_word = []
    for w in ws:
        s = score_word(w)
        per_word.append(s)
        for k in total:
            total[k] += s[k]
    evidence = sum(total.values())
    scores = {k: round(v, 1) for k, v in total.items()}
    if not ws or evidence == 0:
        return Detection(None, "fi", 0.0, "No language can be told from the lyrics. Choose one.", scores, len(ws))
    guess = max(total, key=total.get)
    conf = total[guess] / evidence
    # a mix: both languages carry a real share of the words
    # a word counts for a language when it carries clear evidence of it (a common word, its own
    # letters), not just a weak hint like an ending ("pim pom pum" end in consonants)
    lead = lambda k: sum(1 for s in per_word if s[k] >= 1.5 and s[k] >= max(s.values()))  # noqa: E731
    fi_words, en_words = lead("fi"), lead("en")
    minority = min(total["fi"], total["en"]) / max(1e-9, total["fi"] + total["en"])
    if min(fi_words, en_words) >= max(3, 0.25 * len(ws)) and minority >= 0.2:
        return Detection(None, guess, round(conf, 2),
                         "The lyrics mix Finnish and English. Choose the language the song is sung in.",
                         scores, len(ws))
    if guess == "other" and conf >= 0.4:
        return Detection(None, "other", round(conf, 2),
                         "The lyrics look like another language (e.g. Swedish or German). Chimera sings only Finnish and English.",
                         scores, len(ws))
    if evidence < min_evidence or conf < min_confidence:
        return Detection(None, guess, round(conf, 2),
                         f"The language isn't certain (most likely {NAMES[guess]}). Choose one.", scores, len(ws))
    return Detection(guess, guess, round(conf, 2), f"Detected: {NAMES[guess]}.", scores, len(ws))
