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

/// The Finnish vowel quality reaches the sound: LPC F1/F2 at the midpoint of a long vowel in a
/// rendered word land near the Finnish table, and the back vowels sit well behind the English
/// rendering of the same word (measured, male: /u/ F2 799 Hz fi vs 1043 en, /o/ 828 vs 947,
/// /ɑ/ 1065 vs 1352; /e/ 1892, /ø/ 1531).
#[test]
fn finnish_vowels_reach_the_audio() {
    use chimera::analysis::lpc::{FormantOpts, estimate_formants};
    use chimera::anatomy::human::BODY_MALE;
    use chimera::phonetics::planner::fi_vowel_table;
    use chimera::voice::human_voice::{HumanVoice, SourcePatch};
    const FS: f64 = 48000.0;
    let f12 = |w: &str, v: &str, lang: Option<Language>| {
        let mut segs = word(w);
        segs.last_mut().unwrap().word_end = Some(true);
        let plan = plan_utterance(&segs, &PlanOptions { body: "male".into(), t0: 0.05, f0: Some(110.0), language: lang, ..Default::default() });
        let mut voice = HumanVoice::new(FS, BODY_MALE, 2);
        voice.set_source(&SourcePatch::f0(110.0));
        voice.schedule(&plan.gestures);
        let mut out = vec![0f32; (FS * (plan.end + 0.3)) as usize];
        for c in out.chunks_mut(128) {
            voice.render(c);
        }
        let s = plan.segments.iter().find(|s| s.ipa == v).unwrap();
        let (c, len) = (((s.t0 + s.t1) / 2.0 * FS) as usize, (0.025 * FS) as usize);
        let fr: Vec<f64> = (0..len / 4).map(|k| (0..4).map(|j| out[c - len / 2 + 4 * k + j] as f64).sum::<f64>() / 4.0).collect();
        let fm = estimate_formants(&fr, FS / 4.0, FormantOpts { order: Some(14), max_bw: Some(700.0), ..Default::default() });
        (fm[0].freq, fm[1].freq)
    };
    for (w, v, back) in [("tuuli", "u", true), ("kooma", "o", true), ("maata", "ɑ", true), ("teema", "e", false), ("nööri", "ø", false)] {
        let (f1, f2) = f12(w, v, Some(Language::Finnish));
        let t = &fi_vowel_table()["male"][v].formants;
        assert!((f1 / t[0] - 1.0).abs() < 0.15, "{w} /{v}/ F1 {f1:.0} vs table {}", t[0]);
        assert!((f2 / t[1] - 1.0).abs() < 0.12, "{w} /{v}/ F2 {f2:.0} vs table {}", t[1]);
        if back {
            let (_, en2) = f12(w, v, None);
            assert!(f2 < 0.92 * en2, "{w} /{v}/ F2 fi {f2:.0} not behind en {en2:.0}");
        }
    }
}

// ---------------------------------------------------------------- R, S, T in rendered speech

/// A Finnish word rendered: the plan, the samples, and per control block (128 samples) the
/// narrowest oral area (cm²) and the glottis's voicing (0..1).
struct Rendered {
    plan: chimera::phonetics::Plan,
    out: Vec<f32>,
    area: Vec<f64>,
    voicing: Vec<f64>,
}

const FS: f64 = 48000.0;
const BLOCK: f64 = 128.0 / FS;
const VOICES: [(&str, f64); 2] = [("male", 112.0), ("female", 205.0)];

fn render_fi(w: &str, body: &str, f0: f64) -> Rendered {
    use chimera::anatomy::human::{BODY_FEMALE, BODY_MALE};
    use chimera::voice::human_voice::{HumanVoice, SourcePatch};
    let mut segs = word(w);
    segs.last_mut().unwrap().word_end = Some(true);
    let plan = plan_utterance(&segs, &PlanOptions { body: body.into(), t0: 0.05, f0: Some(f0), language: Some(Language::Finnish), ..Default::default() });
    let mut v = HumanVoice::new(FS, if body == "female" { BODY_FEMALE } else { BODY_MALE }, 2);
    v.set_source(&SourcePatch::f0(f0));
    v.schedule(&plan.gestures);
    let mut out = vec![0f32; (FS * (plan.end + 0.2)) as usize];
    let (mut area, mut voicing) = (Vec::new(), Vec::new());
    for c in out.chunks_mut(128) {
        v.render(c);
        area.push(v.airway.or_areas.iter().cloned().fold(f64::INFINITY, f64::min));
        voicing.push(v.glottis.voicing);
    }
    Rendered { plan, out, area, voicing }
}

impl Rendered {
    fn block(&self, t: f64) -> usize {
        ((t / BLOCK) as usize).min(self.area.len() - 1)
    }
    fn rms(&self, a: f64, b: f64) -> f64 {
        let (a, b) = ((a * FS) as usize, (b * FS) as usize);
        (self.out[a..b].iter().map(|x| (*x as f64).powi(2)).sum::<f64>() / (b - a).max(1) as f64).sqrt()
    }
    fn loudest_vowel(&self) -> f64 {
        self.plan.segments.iter().filter(|s| s.kind == "vowel").map(|s| self.rms(s.t0, s.t1)).fold(0.0, f64::max)
    }
    /// 4 ms frame levels (dB re the loudest vowel) over [a, b]
    fn frames_db(&self, a: f64, b: f64) -> Vec<f64> {
        let v = self.loudest_vowel();
        let mut out = Vec::new();
        let mut t = a;
        while t + 0.004 <= b {
            out.push(20.0 * (self.rms(t, t + 0.004) / v + 1e-9).log10());
            t += 0.004;
        }
        out
    }
    fn seg(&self, ipa: &str, nth: usize) -> &PlannedSegment {
        self.plan.segments.iter().filter(|s| s.ipa == ipa).nth(nth).unwrap_or_else(|| panic!("no {ipa} #{nth}"))
    }
    /// share of [a, b] with the folds vibrating
    fn voiced(&self, a: f64, b: f64) -> f64 {
        let (x, y) = (self.block(a), self.block(b));
        (x..y).filter(|&k| self.voicing[k] > 0.5).count() as f64 / (y - x).max(1) as f64
    }
}

/// Finnish /r/ is a run of brief, light, voiced tip contacts: a tap between vowels, a trill of
/// two word-initially and before a consonant, three or more when long. The generic trill merged
/// its contacts into one closure: /r/ came out as silence and a click, and in "perkele" the /k/
/// closure squeezed the air trapped behind the tip into a pop 1.5 dB below the vowel's level.
/// Sealed contacts then stopped the voicing (trills voiced for 26–52 % of their length).
#[test]
fn finnish_r_is_voiced_contacts_and_does_not_pop() {
    for (body, f0) in VOICES {
        for (w, at_least, at_most, voiced) in [("perkele", 2, 3, 0.5), ("ranta", 2, 2, 0.75), ("tarra", 3, 4, 0.9), ("kuori", 1, 1, 0.9), ("kirsikka", 1, 2, 0.8), ("moottoripyörä", 1, 1, 0.9)] {
            let r = render_fi(w, body, f0);
            let s = r.seg("r", 0);
            // contacts: runs of blocks with the tract narrowed to a light contact, inside the /r/
            let (a, b) = (r.block(s.t0 - 0.005), r.block(s.t1));
            let (mut contacts, mut run, mut sealed, mut longest_seal) = (0, 0, 0, 0);
            for k in a..b {
                if r.area[k] < 0.045 {
                    run += 1;
                    if run == 1 {
                        contacts += 1;
                    }
                } else {
                    run = 0;
                }
                sealed = if r.area[k] < 0.005 { sealed + 1 } else { 0 };
                longest_seal = longest_seal.max(sealed);
            }
            assert!((at_least..=at_most).contains(&contacts), "{body} {w}: {contacts} contacts");
            let v = r.voiced(s.t0, s.t1);
            assert!(v >= voiced, "{body} {w}: the /r/ is voiced for {:.0} % of its length", v * 100.0);
            // a contact never becomes a stop closure (before /s/ it used to: "kirtsikka")
            if w != "perkele" {
                assert!((longest_seal as f64) * BLOCK < 0.012, "{body} {w}: the /r/ seals for {:.0} ms", longest_seal as f64 * BLOCK * 1000.0);
            }
            // each contact dips the level well below the open phases
            let db = r.frames_db(s.t0, s.t1);
            let (lo, hi) = db.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |(l, h), &x| (l.min(x), h.max(x)));
            assert!(hi - lo > 8.0, "{body} {w}: the /r/ level only varies {:.1} dB", hi - lo);
        }
        // no pop: the /k/ closure of "perkele" stays quiet. The pop was -1.5 dB (re the loudest
        // vowel); the seal itself leaves a small transient (-17 to -22 dB here, -26 dB in "ata")
        let r = render_fi("perkele", body, f0);
        let k = r.seg("k", 0);
        let worst = r.frames_db(k.t0, k.t1 - 0.01).into_iter().fold(f64::NEG_INFINITY, f64::max);
        assert!(worst < -12.0, "{body} perkele: {worst:.1} dB inside the /k/ closure");
    }
}

/// Finnish /p t k/ are unaspirated: voicing starts 9–25 ms after the release (Suomi 1980: VOT
/// 9/11/20 ms word-initially, 11/16/25 ms medially). With the English glottal timing it took
/// 22–29 ms, an aspirated [tʰ] that ate the short vowel after it.
#[test]
fn finnish_stops_have_short_vot() {
    for (body, f0) in VOICES {
        for (w, c, lo, hi) in [("pata", "p", 0.0, 0.016), ("pata", "t", 0.006, 0.022), ("tikka", "t", 0.006, 0.022), ("kukka", "k", 0.012, 0.032), ("satama", "t", 0.006, 0.022)] {
            let r = render_fi(w, body, f0);
            let s = r.seg(c, 0);
            let mid = r.block((s.t0 + s.t1) / 2.0);
            let rel = (mid..r.area.len()).find(|&k| r.area[k] > 0.02).unwrap();
            let on = (rel..r.voicing.len()).find(|&k| r.voicing[k] > 0.5).unwrap();
            let vot = (on - rel) as f64 * BLOCK;
            assert!((lo..=hi).contains(&vot), "{body} {w} /{c}/: VOT {:.0} ms", vot * 1000.0);
        }
    }
}

/// Short Finnish vowels between voiceless consonants keep their voicing: the /s/ glottal
/// opening started 45 ms early and the /kk/ dorsum approached 54 ms ahead ("kissa" /i/ voiced
/// for 24 of 70 ms, "kukka" /u/ for 31 %), and after /s/ the /t/ of "satama" sealed 30 ms early
/// with the tip still high, leaving ~10 ms of open /a/.
#[test]
fn finnish_short_vowels_keep_their_voicing() {
    for (body, f0) in VOICES {
        for (w, v, min) in [("kissa", "i", 0.5), ("kukka", "u", 0.5), ("satama", "ɑ", 0.6), ("sitten", "i", 0.5), ("moottoripyörä", "o", 0.6)] {
            let r = render_fi(w, body, f0);
            let s = if w == "moottoripyörä" { r.seg(v, 1) } else { r.seg(v, 0) };
            let f = r.voiced(s.t0, s.t1);
            assert!(f >= min, "{body} {w} /{v}/: voiced {:.0} % of its length", f * 100.0);
        }
        // the /t/ after s·a / s·i seals on time, not inside the vowel
        for w in ["satama", "sitten"] {
            let r = render_fi(w, body, f0);
            let t = r.seg("t", 0);
            let seal = (r.block(t.t0 - 0.04)..r.block(t.t1)).find(|&k| r.area[k] < 0.005).unwrap() as f64 * BLOCK;
            assert!((seal - t.t0).abs() < 0.015, "{body} {w}: /t/ seals {:+.0} ms from its start", (seal - t.t0) * 1000.0);
        }
    }
}

/// Finnish /s/ has its constriction from the start, voiceless, and no breathy [h] ahead of it:
/// the constriction used to form over the whole segment (0.30 cm² at its start, 0.14 at its end;
/// 2.1× its narrowest at 20 %, now at most 1.3×) behind an open glottis, so a word began
/// "h-saatana".
#[test]
fn finnish_s_forms_at_its_onset() {
    for (body, f0) in VOICES {
        for w in ["saatana", "kissa", "lasi"] {
            let r = render_fi(w, body, f0);
            let s = r.seg("s", 0);
            let d = s.t1 - s.t0;
            let at = |f: f64| r.area[r.block(s.t0 + f * d)];
            let narrowest = (r.block(s.t0)..r.block(s.t1)).map(|k| r.area[k]).fold(f64::INFINITY, f64::min);
            assert!(at(0.2) < 1.35 * narrowest, "{body} {w}: /s/ at 20 % is {:.3} cm², narrowest {narrowest:.3}", at(0.2));
            assert!(r.voiced(s.t0 + 0.2 * d, s.t1 - 0.2 * d) < 0.05, "{body} {w}: /s/ is voiced");
        }
        // "saatana": what comes before the /s/ is the /s/ starting, not a wide-open [h]
        let r = render_fi("saatana", body, f0);
        let s = r.seg("s", 0);
        let pre = (r.block(s.t0 - 0.03)..r.block(s.t0)).filter(|&k| r.rms(k as f64 * BLOCK, (k + 1) as f64 * BLOCK) > 0.1 * r.rms(s.t0, s.t1)).all(|k| r.area[k] < 0.3);
        assert!(pre, "{body} saatana: noise before the /s/ through an open tract");
    }
}
