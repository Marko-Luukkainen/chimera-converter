//! Finnish text → phoneme segments. Finnish spelling is close to phonemic, so there is no
//! dictionary: letters map to IPA, a doubled letter is one long segment ([`Segment::long`]),
//! ⟨ng⟩ is a long [ŋː], ⟨n⟩ before ⟨k⟩ is [ŋ], and ⟨h⟩ between vowels is voiced [ɦ].
//!
//! Syllable nuclei follow the diphthong rules: a vowel + i, a vowel + u/y, and the opening
//! diphthongs ie uo yö only in the first syllable; any other pair of vowels is two syllables
//! (ra-di-o). A diphthong is one segment ("ɑi", "uo"); the planner glides between its parts. Primary stress is on the first syllable, secondary stress on the odd syllables after
//! it but never on the last (kir-joit-ta-mi-nen → 1 0 2 0 0).
//!
//! A question mark keeps the statement fall: Finnish marks questions with -ko/-kö or a question
//! word, not with a final rise.
//!
//! Not modelled yet: boundary gemination (rajageminaatio: "tule tänne" [tulet tænːe]), stress
//! inside compounds written as one word, the coda allophones of /h/ ([ç x]), loanword exceptions.

use super::english::{Phrase, is_phrase_punct, split_keeping};
use super::planner::is_vowel;
use super::syllables::{LyricRules, SyllableParts, lyrics_with};
use super::{Intonation, Segment, Syllable};
use crate::anatomy::human::BodyMix;

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

/// One word (no spaces or hyphens) → segments with stress on each syllable nucleus. A diphthong
/// is one segment of two vowels ("ɑi"), which the planner splits into its two targets.
fn simple_word(w: &str) -> Vec<Segment> {
    let ph = phones(w);
    let mut segs: Vec<Segment> = Vec::with_capacity(ph.len());
    // the segment index of each syllable nucleus
    let mut nuclei: Vec<usize> = Vec::new();
    let mut i = 0;
    while i < ph.len() {
        let p = &ph[i];
        let mut seg = Segment { ipa: p.ipa.to_string(), stress: Some(0), long: p.long.then_some(true), ..Default::default() };
        let Some(a) = p.vowel else {
            segs.push(seg);
            i += 1;
            continue;
        };
        let first = nuclei.is_empty();
        let joins = !p.long && ph.get(i + 1).is_some_and(|n| !n.long && n.vowel.is_some_and(|b| is_diphthong(a, b, first)));
        if joins {
            seg.ipa.push_str(ph[i + 1].ipa);
        }
        nuclei.push(segs.len());
        segs.push(seg);
        i += if joins { 2 } else { 1 };
    }
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

// ---------------------------------------------------------------- syllables (singing)

/// One word's segments → syllables. A consonant before a vowel starts the syllable, the other
/// consonants close the one before (kis-sa, kart-ta, ra-di-o); a word's leading consonants are
/// its first onset (stres-si). A geminate splits across the boundary, so in singing its closure
/// falls between the two notes: "kissa" → [kis] [sɑ].
pub fn syllabify(segs: &[Segment]) -> Vec<SyllableParts> {
    let vi: Vec<usize> = segs.iter().enumerate().filter(|(_, s)| is_vowel(&s.ipa, BodyMix::MALE)).map(|(i, _)| i).collect();
    let Some(&first) = vi.first() else { return Vec::new() };
    let mut out = Vec::with_capacity(vi.len());
    let mut onset: Vec<Segment> = segs[..first].to_vec();
    for (n, &v) in vi.iter().enumerate() {
        let (coda, next_onset) = match vi.get(n + 1) {
            None => (segs[v + 1..].to_vec(), Vec::new()),
            Some(&next) => match segs[v + 1..next].split_last() {
                None => (Vec::new(), Vec::new()),
                Some((last, rest)) => {
                    let short = Segment { long: None, ..last.clone() };
                    let mut coda = rest.to_vec();
                    if last.long == Some(true) {
                        coda.push(short.clone());
                    }
                    (coda, vec![short])
                }
            },
        };
        out.push(SyllableParts { onset: std::mem::take(&mut onset), nucleus: segs[v].clone(), coda });
        onset = next_onset;
    }
    out
}

/// A written vowel letter as its base vowel (accented loan letters too), or None.
fn base_vowel(c: char) -> Option<char> {
    let c = c.to_lowercase().next()?;
    Some(match c {
        'a' | 'e' | 'i' | 'o' | 'u' | 'y' | 'ä' | 'ö' => c,
        'å' | 'ó' | 'ò' | 'ô' | 'õ' => 'o',
        'é' | 'è' | 'ê' | 'ë' => 'e',
        'á' | 'à' | 'â' => 'a',
        'í' | 'ì' | 'î' | 'ï' => 'i',
        'ú' | 'ù' | 'û' => 'u',
        'ü' => 'y',
        _ => return None,
    })
}

/// A written Finnish word split into `n` syllables for display, by the same rules as
/// [`syllabify`] on the letters (kis-sa, ken-gät, maa-il-ma, ra-di-o). When the letters give a
/// different count (loan spellings), the word is held whole and the rest continue ("~").
pub fn hyphenate(w: &str, n: usize) -> Vec<String> {
    let c: Vec<char> = w.chars().collect();
    // the letter index where each nucleus starts and ends (exclusive)
    let mut nuclei: Vec<(usize, usize)> = Vec::new();
    let mut i = 0;
    while i < c.len() {
        let Some(a) = base_vowel(c[i]) else {
            i += 1;
            continue;
        };
        let next = c.get(i + 1).copied().and_then(base_vowel);
        // a long vowel, or a diphthong whose second vowel is not itself long
        let long = next == Some(a);
        let diphthong = next.is_some_and(|b| is_diphthong(a, b, nuclei.is_empty())) && c.get(i + 2).copied().and_then(base_vowel) != next;
        let len = if long || diphthong { 2 } else { 1 };
        nuclei.push((i, i + len));
        i += len;
    }
    if nuclei.len() != n || n <= 1 {
        let mut out = vec![w.to_string()];
        out.extend(std::iter::repeat_n("~".to_string(), n.saturating_sub(1)));
        return out;
    }
    let mut cuts = vec![0];
    for k in 1..nuclei.len() {
        let (end, start) = (nuclei[k - 1].1, nuclei[k].0);
        cuts.push(if start > end { start - 1 } else { start });
    }
    cuts.push(c.len());
    cuts.windows(2).map(|p| c[p[0]..p[1]].iter().collect()).collect()
}

fn is_letter(c: char) -> bool {
    c.is_alphabetic() || c == '\''
}

/// Finnish lyrics → sung syllables (the same marks as English lyrics: a lone "-" or "~" holds the
/// previous vowel onto the next note, typed hyphens split a word).
pub fn lyrics_to_syllables(text: &str) -> Vec<Syllable> {
    lyrics_with(text, &LyricRules { letter: is_letter, syllables: &|w| syllabify(&word(w)), spell: hyphenate })
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

