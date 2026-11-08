//! Finnish text → phoneme segments. Finnish spelling is close to phonemic, so there is no
//! dictionary: letters map to IPA, a doubled letter is one long segment ([`Segment::long`]),
//! ⟨ng⟩ is a long [ŋː], ⟨n⟩ before ⟨k⟩ is [ŋ], and ⟨h⟩ between vowels is voiced [ɦ].
//!
//! Syllable nuclei follow the diphthong rules: a vowel + i, a vowel + u/y, and the opening
//! diphthongs ie uo yö only in the first syllable; any other pair of vowels is two syllables
//! (ra-di-o). Primary stress is on the first syllable, secondary stress on the odd syllables after
//! it but never on the last (kir-joit-ta-mi-nen → 1 0 2 0 0).
//!
//! A question mark keeps the statement fall: Finnish marks questions with -ko/-kö or a question
//! word, not with a final rise.
//!
//! Not modelled yet: boundary gemination (rajageminaatio: "tule tänne" [tulet tænːe]), stress
//! inside compounds written as one word, the coda allophones of /h/ ([ç x]), loanword exceptions.

use super::english::{Phrase, is_phrase_punct, split_keeping};
use super::{Intonation, Segment};

fn vowel_ipa(c: char) -> Option<&'static str> {
    Some(match c {
        'a' => "ɑ",
        'e' => "e",
        'i' => "i",
        'o' => "o",
        'u' => "u",
        'y' => "y",
        'ä' => "æ",
        'ö' => "ø",
        _ => return None,
    })
}

fn consonant_ipa(c: char) -> Option<&'static str> {
    Some(match c {
        'p' => "p",
        't' => "t",
        'k' => "k",
        'b' => "b",
        'd' => "d",
        'g' => "g",
        'f' => "f",
        's' => "s",
        'h' => "h",
        'j' => "j",
        'l' => "l",
        'm' => "m",
        'n' => "n",
        'r' => "r",
        'v' => "ʋ",
        'š' => "ʃ",
        'ž' => "ʒ",
        _ => return None,
    })
}

/// Loan letters and accented vowels → native spelling (pizza → pitsa, Åbo → obo, café → cafe).
fn normalize(w: &str) -> String {
    let w = w.replace("zz", "ts");
    let chars: Vec<char> = w.chars().collect();
    let mut out = String::with_capacity(w.len() + 4);
    for (i, &c) in chars.iter().enumerate() {
        let next = chars.get(i + 1).copied();
        match c {
            'å' | 'ó' | 'ò' | 'ô' | 'õ' => out.push('o'),
            'é' | 'è' | 'ê' | 'ë' => out.push('e'),
            'á' | 'à' | 'â' => out.push('a'),
            'í' | 'ì' | 'î' | 'ï' => out.push('i'),
            'ú' | 'ù' | 'û' => out.push('u'),
            'ü' => out.push('y'),
            'w' => out.push('v'),
            'q' => out.push('k'),
            'x' => out.push_str("ks"),
            'z' => out.push_str("ts"),
            'ß' => out.push_str("ss"),
            // c is [s] before a front vowel (Cecilia), [k] elsewhere (Carl)
            'c' => out.push(if matches!(next, Some('e' | 'i' | 'y' | 'ä' | 'ö')) { 's' } else { 'k' }),
            _ => out.push(c),
        }
    }
    out
}

/// One phone of a word: its IPA, whether it is long, and its vowel letter (for the diphthong rules).
struct Phone {
    ipa: &'static str,
    long: bool,
    vowel: Option<char>,
}

fn phones(w: &str) -> Vec<Phone> {
    let c: Vec<char> = normalize(w).chars().filter(|c| c.is_alphabetic()).collect();
    let is_v = |i: usize| c.get(i).is_some_and(|&ch| vowel_ipa(ch).is_some());
    let mut out = Vec::with_capacity(c.len());
    let mut i = 0;
    while i < c.len() {
        let ch = c[i];
        let next = c.get(i + 1).copied();
        if ch == 'n' && next == Some('g') {
            out.push(Phone { ipa: "ŋ", long: true, vowel: None });
            i += 2;
            continue;
        }
        if ch == 'n' && next == Some('k') {
            out.push(Phone { ipa: "ŋ", long: false, vowel: None });
            i += 1;
            continue;
        }
        let long = next == Some(ch);
        if let Some(ipa) = vowel_ipa(ch) {
            out.push(Phone { ipa, long, vowel: Some(ch) });
        } else if let Some(ipa) = consonant_ipa(ch) {
            let voiced_h = ch == 'h' && !long && i > 0 && is_v(i - 1) && is_v(i + 1);
            out.push(Phone { ipa: if voiced_h { "ɦ" } else { ipa }, long, vowel: None });
        }
        i += if long { 2 } else { 1 };
    }
    out
}

/// Whether two short vowels make one nucleus. `first`: in the word's first syllable.
fn is_diphthong(a: char, b: char, first: bool) -> bool {
    match b {
        'i' => matches!(a, 'a' | 'e' | 'o' | 'u' | 'y' | 'ä' | 'ö'),
        'u' => matches!(a, 'a' | 'e' | 'i' | 'o'),
        'y' => matches!(a, 'e' | 'i' | 'ä' | 'ö'),
        'e' => first && a == 'i',
        'o' => first && a == 'u',
        'ö' => first && a == 'y',
        _ => false,
    }
}

/// One word (no spaces or hyphens) → segments with stress on each syllable nucleus.
fn simple_word(w: &str) -> Vec<Segment> {
    let ph = phones(w);
    // the phone index where each syllable nucleus starts
    let mut nuclei: Vec<usize> = Vec::new();
    let mut i = 0;
    while i < ph.len() {
        let Some(a) = ph[i].vowel else {
            i += 1;
            continue;
        };
        let first = nuclei.is_empty();
        nuclei.push(i);
        let joins = !ph[i].long && ph.get(i + 1).is_some_and(|n| !n.long && n.vowel.is_some_and(|b| is_diphthong(a, b, first)));
        i += if joins { 2 } else { 1 };
    }
    let mut segs: Vec<Segment> = ph
        .iter()
        .map(|p| Segment { ipa: p.ipa.to_string(), stress: Some(0), long: p.long.then_some(true), ..Default::default() })
        .collect();
    let n = nuclei.len();
    for (k, &at) in nuclei.iter().enumerate() {
        segs[at].stress = Some(if k == 0 {
            1
        } else if k % 2 == 0 && k + 1 < n {
            2
        } else {
            0
        });
    }
    segs
}

/// One word → segments. A hyphenated compound (linja-auto) stresses each part.
pub fn word(w: &str) -> Vec<Segment> {
    let lower = w.to_lowercase();
    lower.split('-').flat_map(simple_word).collect()
}

/// Text → phrases of segments (same phrasing and pauses as the English G2P).
pub fn to_phrases(text: &str) -> Vec<Phrase> {
    let mut phrases: Vec<Phrase> = Vec::new();
    let normalized = expand_numbers(&text.replace('’', "'"));
    let parts = split_keeping(&normalized, is_phrase_punct);
    let mut words: Vec<String> = Vec::new();
    let mut flush = |delim: &str, words: &mut Vec<String>| {
        if words.is_empty() {
            return;
        }
        let mut segs: Vec<Segment> = Vec::new();
        let mut said: Vec<String> = Vec::new();
        for w in words.iter() {
            let mut ws = word(w);
            let Some(last) = ws.last_mut() else { continue };
            last.word_end = Some(true);
            segs.append(&mut ws);
            said.push(w.clone());
        }
        let pause = if delim.contains(['.', '!', '?']) {
            0.35
        } else if !delim.is_empty() {
            0.18
        } else {
            0.3
        };
        words.clear();
        if !segs.is_empty() {
            phrases.push(Phrase { segments: segs, intonation: Intonation::Statement, pause, words: said });
        }
    };
    for part in &parts {
        if !part.is_empty() && part.chars().all(is_phrase_punct) {
            flush(part, &mut words);
        } else {
            let lower = part.to_lowercase();
            words.extend(lower.split(|c: char| !(c.is_alphabetic() || c == '\'' || c == '-')).filter(|w| w.chars().any(char::is_alphabetic)).map(str::to_string));
        }
    }
    flush("", &mut words);
    phrases
}

// ---------------------------------------------------------------- numbers
const ONES: [&str; 10] = ["nolla", "yksi", "kaksi", "kolme", "neljä", "viisi", "kuusi", "seitsemän", "kahdeksan", "yhdeksän"];

/// 1..=999 as words. Tens and ones stay separate words so each gets a stress
/// ("kaksikymmentä kolme"); hundreds and teens are one word ("kaksisataa", "yksitoista").
fn under_thousand(n: u64, out: &mut Vec<String>) {
    let (h, r) = ((n / 100) as usize, n % 100);
    match h {
        0 => {}
        1 => out.push("sata".into()),
        _ => out.push(format!("{}sataa", ONES[h])),
    }
    let r = r as usize;
    match r {
        0 => {}
        1..=9 => out.push(ONES[r].into()),
        10 => out.push("kymmenen".into()),
        11..=19 => out.push(format!("{}toista", ONES[r - 10])),
        _ => {
            out.push(format!("{}kymmentä", ONES[r / 10]));
            if !r.is_multiple_of(10) {
                out.push(ONES[r % 10].into());
            }
        }
    }
}

/// A cardinal number (nominative) as words, up to 999 999 999.
pub fn number_words(n: u64) -> Vec<String> {
    if n == 0 {
        return vec![ONES[0].into()];
    }
    let mut out = Vec::new();
    let (mil, th, rest) = (n / 1_000_000, (n / 1000) % 1000, n % 1000);
    for (part, one, many) in [(mil, "miljoona", "miljoonaa"), (th, "tuhat", "tuhatta")] {
        match part {
            0 => {}
            1 => out.push(one.into()),
            _ => {
                under_thousand(part, &mut out);
                out.push(many.into());
            }
        }
    }
    under_thousand(rest, &mut out);
    out
}

/// Digit runs → number words. A run with a leading zero, or longer than nine digits, is read digit
/// by digit (phone numbers, codes).
fn expand_numbers(t: &str) -> String {
    let mut out = String::with_capacity(t.len());
    let mut run = String::new();
    let emit = |run: &mut String, out: &mut String| {
        if run.is_empty() {
            return;
        }
        let words: Vec<String> = if (run.len() > 1 && run.starts_with('0')) || run.len() > 9 {
            run.bytes().map(|d| ONES[(d - b'0') as usize].to_string()).collect()
        } else {
            number_words(run.parse().unwrap_or(0))
        };
        out.push(' ');
        out.push_str(&words.join(" "));
        out.push(' ');
        run.clear();
    };
    for c in t.chars() {
        if c.is_ascii_digit() {
            run.push(c);
        } else {
            emit(&mut run, &mut out);
            out.push(c);
        }
    }
    emit(&mut run, &mut out);
    out
}

