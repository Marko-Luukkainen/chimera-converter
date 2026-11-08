//! Finnish G2P: letters, quantity, diphthongs and syllables, stress, numbers, phrasing.
use chimera::phonetics::Intonation;
use chimera::phonetics::finnish::{number_words, to_phrases, word};
use chimera::phonetics::planner::{PlanOptions, plan_utterance};

/// segments as "k ˈi sː ɑ" (ˈ primary, ˌ secondary, ː long)
fn show(w: &str) -> String {
    word(w)
        .iter()
        .map(|s| {
            let mark = match s.stress {
                Some(1) => "ˈ",
                Some(2) => "ˌ",
                _ => "",
            };
            format!("{mark}{}{}", s.ipa, if s.long == Some(true) { "ː" } else { "" })
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[test]
fn letters_and_length() {
    assert_eq!(show("kissa"), "k ˈi sː ɑ");
    assert_eq!(show("tuli"), "t ˈu l i");
    assert_eq!(show("tuuli"), "t ˈuː l i");
    assert_eq!(show("tulli"), "t ˈu lː i");
    assert_eq!(show("pöytä"), "p ˈø y t æ");
    assert_eq!(show("vesi"), "ʋ ˈe s i");
}

#[test]
fn velar_nasal_and_voiced_h() {
    assert_eq!(show("kenkä"), "k ˈe ŋ k æ");
    assert_eq!(show("kengät"), "k ˈe ŋː æ t");
    assert_eq!(show("raha"), "r ˈɑ ɦ ɑ");
    assert_eq!(show("lehti"), "l ˈe h t i");
}

#[test]
fn diphthongs_and_syllables() {
    // ie uo yö are diphthongs only in the first syllable
    assert_eq!(show("tie"), "t ˈi e");
    assert_eq!(show("suomi"), "s ˈu o m i");
    // ra-di-o: the third syllable is the last, so no secondary stress
    assert_eq!(show("radio"), "r ˈɑ d i o");
    // kor-ke-aa: a long vowel after a short one is its own syllable
    assert_eq!(show("korkeaa"), "k ˈo r k e ɑː");
    // maa-il-ma: a long vowel never joins the next vowel
    assert_eq!(show("maailma"), "m ˈɑː i l m ɑ");
}

#[test]
fn secondary_stress_on_odd_syllables_but_not_the_last() {
    // kir-joit-ta-mi-nen
    assert_eq!(show("kirjoittaminen"), "k ˈi r j o i tː ˌɑ m i n e n");
    assert_eq!(show("talo"), "t ˈɑ l o");
    // a hyphenated compound stresses each part
    assert_eq!(show("linja-auto"), "l ˈi n j ɑ ˈɑ u t o");
}

#[test]
fn loan_letters() {
    assert_eq!(show("pizza"), "p ˈi t s ɑ");
    assert_eq!(show("taxi"), "t ˈɑ k s i");
    assert_eq!(show("watti"), "ʋ ˈɑ tː i");
}

#[test]
fn numbers() {
    assert_eq!(number_words(0), ["nolla"]);
    assert_eq!(number_words(12), ["kaksitoista"]);
    assert_eq!(number_words(23), ["kaksikymmentä", "kolme"]);
    assert_eq!(number_words(100), ["sata"]);
    assert_eq!(number_words(1917), ["tuhat", "yhdeksänsataa", "seitsemäntoista"]);
    assert_eq!(number_words(2026), ["kaksi", "tuhatta", "kaksikymmentä", "kuusi"]);
    assert_eq!(to_phrases("3 kissaa")[0].words, ["kolme", "kissaa"]);
    // a leading zero is read digit by digit
    assert_eq!(to_phrases("040")[0].words, ["nolla", "neljä", "nolla"]);
}

#[test]
fn phrases_and_questions_do_not_rise() {
    let p = to_phrases("Hyvää huomenta! Mitä kuuluu?");
    assert_eq!(p.len(), 2);
    assert_eq!(p[0].words, ["hyvää", "huomenta"]);
    assert!(p.iter().all(|p| p.intonation == Intonation::Statement));
    assert_eq!(p[1].segments.last().unwrap().word_end, Some(true));
}

/// tuli / tuuli / tulli: the long segment is clearly longer than its short counterpart.
#[test]
fn quantity_reaches_the_plan() {
    let dur = |w: &str, ipa: &str| {
        let mut segs = word(w);
        segs.last_mut().unwrap().word_end = Some(true);
        let plan = plan_utterance(&segs, &PlanOptions::default());
        let s = plan.segments.iter().find(|s| s.ipa == ipa).unwrap();
        s.t1 - s.t0
    };
    let (u, uu) = (dur("tuli", "u"), dur("tuuli", "u"));
    let (l, ll) = (dur("tuli", "l"), dur("tulli", "l"));
    assert!(uu / u > 1.7, "vowel ratio {}", uu / u);
    assert!(ll / l > 1.7, "consonant ratio {}", ll / l);
}
