//! Finnish G2P: letters, quantity, diphthongs and syllables, stress, numbers, phrasing.
use chimera::control::score::ControlKey;
use chimera::phonetics::{Intonation, Language, PlannedSegment};
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
    assert_eq!(show("pöytä"), "p ˈøy t æ");
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
    // a diphthong is one segment; ie uo yö are diphthongs only in the first syllable
    assert_eq!(show("tie"), "t ˈie");
    assert_eq!(show("suomi"), "s ˈuo m i");
    // ra-di-o: the third syllable is the last, so no secondary stress
    assert_eq!(show("radio"), "r ˈɑ d i o");
    // kor-ke-aa: a long vowel after a short one is its own syllable
    assert_eq!(show("korkeaa"), "k ˈo r k e ɑː");
    // maa-il-ma: a long vowel never joins the next vowel
    assert_eq!(show("maailma"), "m ˈɑː i l m ɑ");
    // the opening diphthongs only start a word: ty-ö is a diphthong, but another vowel pair inside a word is two syllables
    assert_eq!(show("yö"), "ˈyø");
    assert_eq!(show("koulu"), "k ˈou l u");
    assert_eq!(show("sauna"), "s ˈɑu n ɑ");
}

/// Every diphthong the G2P can emit expands to two vowel targets in the planner.
#[test]
fn every_diphthong_expands() {
    use chimera::phonetics::planner::diphthong_parts;
    let words = "laiva leipä koira uida lyijy äiti öisin sauna leuka kiuas koulu leyhyä siistiytyä täysi löyly tie suo yö";
    for w in words.split(' ') {
        for s in word(w) {
            if s.ipa.chars().count() > 1 && !["ts"].contains(&s.ipa.as_str()) {
                assert!(diphthong_parts(&s.ipa).is_some(), "{w}: {} does not expand", s.ipa);
            }
        }
    }
}

#[test]
fn secondary_stress_on_odd_syllables_but_not_the_last() {
    // kir-joit-ta-mi-nen
    assert_eq!(show("kirjoittaminen"), "k ˈi r j oi tː ˌɑ m i n e n");
    assert_eq!(show("talo"), "t ˈɑ l o");
    // a hyphenated compound stresses each part
    assert_eq!(show("linja-auto"), "l ˈi n j ɑ ˈɑu t o");
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

/// A Finnish word planned on its own: the planned segments.
fn plan_fi(w: &str, language: Option<Language>) -> Vec<PlannedSegment> {
    let mut segs = word(w);
    segs.last_mut().unwrap().word_end = Some(true);
    plan_utterance(&segs, &PlanOptions { body: "male".into(), f0: Some(110.0), language, ..Default::default() }).segments
}

/// Duration (s) of the n-th planned segment with this IPA.
fn dur_of(plan: &[PlannedSegment], ipa: &str, nth: usize) -> f64 {
    let s = plan.iter().filter(|s| s.ipa == ipa).nth(nth).unwrap_or_else(|| panic!("no {ipa} #{nth}"));
    s.t1 - s.t0
}

/// tuli / tuuli / tulli: the long segment is clearly longer than its short counterpart, with
/// or without the Finnish duration rules.
#[test]
fn quantity_reaches_the_plan() {
    for lang in [None, Some(Language::Finnish)] {
        let (tuli, tuuli, tulli) = (plan_fi("tuli", lang), plan_fi("tuuli", lang), plan_fi("tulli", lang));
        let vowel = dur_of(&tuuli, "u", 0) / dur_of(&tuli, "u", 0);
        let cons = dur_of(&tulli, "l", 0) / dur_of(&tuli, "l", 0);
        assert!(vowel > 1.7, "{lang:?} vowel ratio {vowel}");
        assert!(cons > 1.7, "{lang:?} consonant ratio {cons}");
    }
}

/// The Finnish quantity minimal pairs, measured in the plan: kato / katto / kaato and
/// tuli / tuuli / tulli. Long vowels ~2.2× short in the first syllable, geminate stop closures
/// ~2.3×, geminate sonorants ~1.9×; the second-syllable vowel is half-long only after a light
/// first syllable (kato, tuli), not after a long vowel or a geminate.
#[test]
fn finnish_minimal_pairs() {
    let fi = Some(Language::Finnish);
    let (kato, katto, kaato) = (plan_fi("kato", fi), plan_fi("katto", fi), plan_fi("kaato", fi));
    let r = |a: f64, b: f64| a / b;
    let v1 = r(dur_of(&kaato, "ɑ", 0), dur_of(&kato, "ɑ", 0));
    let c = r(dur_of(&katto, "t", 0), dur_of(&kato, "t", 0));
    assert!((2.0..2.6).contains(&v1), "kaato/kato first vowel {v1}");
    assert!((2.0..2.6).contains(&c), "katto/kato closure {c}");
    // the half-long second vowel: kato's /o/ is longer than katto's and kaato's
    let o_light = dur_of(&kato, "o", 0);
    for (w, p) in [("katto", &katto), ("kaato", &kaato)] {
        let ratio = o_light / dur_of(p, "o", 0);
        assert!((1.3..1.6).contains(&ratio), "kato /o/ vs {w} /o/: {ratio}");
    }
    // the first vowel before a geminate is not lengthened (no English pre-voicing rules)
    assert!((dur_of(&katto, "ɑ", 0) - dur_of(&kato, "ɑ", 0)).abs() < 1e-9);
    let (tuli, tulli) = (plan_fi("tuli", fi), plan_fi("tulli", fi));
    let l = dur_of(&tulli, "l", 0) / dur_of(&tuli, "l", 0);
    assert!((1.7..2.1).contains(&l), "tulli/tuli /l/ {l}");
}

/// Finnish /p t k/ are unaspirated: the glottal opening at a stop release is the small
/// short-lag one, not the wide English aspiration.
#[test]
fn finnish_stops_are_unaspirated() {
    let abduction = |lang: Option<Language>| {
        let mut segs = word("tapa");
        segs.last_mut().unwrap().word_end = Some(true);
        let plan = plan_utterance(&segs, &PlanOptions { body: "male".into(), f0: Some(110.0), language: lang, ..Default::default() });
        plan.gestures.iter().filter(|g| g.label.is_some_and(|l| l.as_str() == "aspiration")).map(|g| g.targets.get(ControlKey::ABDUCTION).unwrap()).fold(0.0f64, f64::max)
    };
    assert!(abduction(None) > 0.3, "English aspirates");
    assert!(abduction(Some(Language::Finnish)) < 0.25, "Finnish does not aspirate");
}

/// A Finnish question does not end in a rise, even when the phrase is marked as one.
#[test]
fn finnish_question_keeps_the_fall() {
    let last_pitch = |lang: Option<Language>| {
        let mut segs = word("tuletko");
        segs.last_mut().unwrap().word_end = Some(true);
        let plan = plan_utterance(&segs, &PlanOptions { body: "male".into(), f0: Some(110.0), intonation: Some(Intonation::Question), language: lang, ..Default::default() });
        plan.gestures.iter().rev().find(|g| g.label.is_some_and(|l| l.as_str() == "pitch")).map(|g| g.targets.get(ControlKey::F0).unwrap()).unwrap()
    };
    assert!(last_pitch(None) > 140.0, "English questions rise");
    assert!(last_pitch(Some(Language::Finnish)) < 100.0, "Finnish questions fall");
}

/// A Finnish plan takes /u/ from the Finnish vowel table (back, F2 well below the American /u/);
/// English plans and Finnish vowels without their own entry (/i/) keep the main table.
#[test]
fn finnish_vowels_come_from_the_finnish_table() {
    use chimera::anatomy::human::ArticKey;
    use chimera::phonetics::planner::{fi_vowel_table, vowel_table};
    let tb_x = |w: &str, ipa: &str, lang: Option<Language>| {
        let mut segs = word(w);
        segs.last_mut().unwrap().word_end = Some(true);
        let plan = plan_utterance(&segs, &PlanOptions { body: "male".into(), f0: Some(110.0), language: lang, ..Default::default() });
        plan.gestures.iter().find(|g| g.label.is_some_and(|l| l.as_str() == ipa)).and_then(|g| g.targets.get(ArticKey::TbX)).unwrap()
    };
    let fi_u = fi_vowel_table()["male"]["u"].artic.get(ArticKey::TbX).unwrap();
    let en_u = vowel_table()["male"]["u"].artic.get(ArticKey::TbX).unwrap();
    assert_eq!(tb_x("tuli", "u", Some(Language::Finnish)), fi_u);
    assert_eq!(tb_x("tuli", "u", None), en_u);
    assert_eq!(tb_x("tuli", "i", Some(Language::Finnish)), vowel_table()["male"]["i"].artic.get(ArticKey::TbX).unwrap());
    // the Finnish back vowels are calibrated well behind the American ones
    for v in ["u", "o", "ɑ"] {
        let (fi, en) = (fi_vowel_table()["male"][v].formants[1], vowel_table()["male"][v].formants[1]);
        assert!(fi < 0.9 * en, "/{v}/ F2 fi {fi} en {en}");
    }
}

/// Finnish /t/ is dental: its tip target is the dental template, and the closure still seals
/// (the template had never been used; mid-closure level measured at -44 dB re the vowel for the
/// male voice, -52 dB for the female, against -39 / -47 dB for the alveolar English /t/).
#[test]
fn finnish_t_is_dental_and_seals() {
    use chimera::anatomy::human::{ArticKey, BODY_FEMALE, BODY_MALE};
    use chimera::voice::human_voice::{HumanVoice, SourcePatch};
    for (body, name, f0) in [(BODY_MALE, "male", 110.0), (BODY_FEMALE, "female", 200.0)] {
        for w in ["ata", "atta"] {
            let mut segs = word(w);
            segs.last_mut().unwrap().word_end = Some(true);
            let plan = plan_utterance(&segs, &PlanOptions { body: name.into(), t0: 0.05, f0: Some(f0), language: Some(Language::Finnish), ..Default::default() });
            let tip = plan.gestures.iter().find(|g| g.label.is_some_and(|l| l.as_str() == "t") && g.targets.get(ArticKey::TtX).is_some()).unwrap();
            assert_eq!(tip.targets.get(ArticKey::TtX), Some(6.85), "{w}: dental tip");
            let mut v = HumanVoice::new(48000.0, body, 2);
            v.set_source(&SourcePatch::f0(f0));
            v.schedule(&plan.gestures);
            let mut out = vec![0f32; (48000.0 * (plan.end + 0.3)) as usize];
            for c in out.chunks_mut(128) {
                v.render(c);
            }
            let rms = |a: f64, b: f64| {
                let (a, b) = ((a * 48000.0) as usize, (b * 48000.0) as usize);
                (out[a..b].iter().map(|x| (*x as f64).powi(2)).sum::<f64>() / (b - a) as f64).sqrt()
            };
            let t = plan.segments.iter().find(|s| s.ipa == "t").unwrap();
            let v0 = plan.segments.iter().find(|s| s.kind == "vowel").unwrap();
            let (mid, h) = ((t.t0 + t.t1) / 2.0, (t.t1 - t.t0) * 0.2);
            let db = 20.0 * (rms(mid - h, mid + h) / rms(v0.t0 + 0.01, v0.t1 - 0.01)).log10();
            assert!(db < -35.0, "{name} {w}: mid-closure only {db:.1} dB below the vowel");
        }
    }
}

/// Sung syllables: a consonant before a vowel starts the syllable, a geminate splits across the
/// boundary, the written word splits the same way for display.
#[test]
fn finnish_lyrics_syllables() {
    use chimera::phonetics::finnish::{hyphenate, lyrics_to_syllables};
    let show = |text: &str| {
        lyrics_to_syllables(text)
            .iter()
            .map(|s| {
                let p = |v: &[chimera::phonetics::Segment]| v.iter().map(|c| c.ipa.as_str()).collect::<String>();
                format!("{}:{}{}{}", s.text, p(&s.onset), s.nucleus.ipa, p(&s.coda))
            })
            .collect::<Vec<_>>()
            .join(" ")
    };
    assert_eq!(show("kissa"), "kis:kis sa:sɑ");
    assert_eq!(show("kengät"), "ken:keŋ gät:ŋæt");
    assert_eq!(show("maailma"), "maa:mɑ il:il ma:mɑ");
    assert_eq!(show("radio"), "ra:rɑ di:di o:o");
    assert_eq!(show("stressi"), "stres:stres si:si");
    assert_eq!(show("Pöytä"), "Pöy:pøy tä:tæ");
    assert_eq!(show("kart-ta"), "kart:kɑrt ta:tɑ");
    assert_eq!(hyphenate("kirjoittaminen", 5), ["kir", "joit", "ta", "mi", "nen"]);
    assert_eq!(hyphenate("taxi", 2), ["ta", "xi"]);
    // a melisma mark holds the vowel; punctuation ends a phrase
    let s = lyrics_to_syllables("Laulan - aina, joo.");
    assert_eq!(s.iter().map(|s| s.text.as_str()).collect::<Vec<_>>(), ["Lau", "lan", "~", "ai", "na", "joo"]);
    assert_eq!(s.iter().map(|s| s.phrase_end).collect::<Vec<_>>(), [false, false, false, false, true, true]);
}

/// The Finnish demo song has one syllable per note, and plans with Finnish rules.
#[test]
fn finnish_demo_song() {
    use chimera::phonetics::finnish::lyrics_to_syllables;
    use chimera::phonetics::sing::{SongOptions, SungNote, plan_song};
    use chimera::phonetics::songs::DEMO_SONGS;
    let song = DEMO_SONGS.iter().find(|s| s.language == Some(Language::Finnish)).expect("a Finnish demo song");
    let syl = lyrics_to_syllables(song.lyrics);
    assert_eq!(syl.len(), song.notes.len(), "{}: {:?}", song.name, syl.iter().map(|s| &s.text).collect::<Vec<_>>());
    let notes: Vec<SungNote> = song.notes.iter().zip(&syl).map(|(n, s)| SungNote { midi: n[0] - 12.0, beats: n[1], syl: s.clone() }).collect();
    let plan = plan_song(&notes, &SongOptions { body: "male".into(), bpm: song.bpm, t0: 0.3, vibrato: 30.0, language: song.language });
    // "Jaakko kulta": the /k/ releases are unaspirated
    let wide = plan.gestures.iter().filter(|g| g.label.is_some_and(|l| l.as_str() == "aspiration")).filter_map(|g| g.targets.get(ControlKey::ABDUCTION)).fold(0.0f64, f64::max);
    assert!(wide < 0.25, "aspiration {wide}");
}
