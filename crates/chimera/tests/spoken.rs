//! Speech at a recording's times (`phonetics::spoken`): the converter's speech style.
use chimera::analysis::pitch::{YinOpts, yin_pitch};
use chimera::anatomy::human::{BODY_MALE, BodyMix};
use chimera::control::score::{ControlKey, GestureScore};
use chimera::phonetics::Language;
use chimera::phonetics::finnish::lyrics_to_syllables;
use chimera::phonetics::spoken::{Contour, SpokenOptions, SpokenSyllable, plan_spoken};
use chimera::voice::human_voice::{HumanVoice, SourcePatch};

const LYRICS: &str = "Hy-vää huo-men-ta, mi-tä kuu-luu?";

/// the syllables of LYRICS at uneven, speech-like times, with a pause after "ta,"
fn syllables() -> Vec<SpokenSyllable> {
    let syl = lyrics_to_syllables(LYRICS);
    let at = [0.40, 0.58, 0.83, 0.97, 1.16, 1.80, 1.95, 2.13, 2.40];
    let mut end: Vec<f64> = at[1..].iter().map(|a| a - 0.02).collect();
    end.push(2.75);
    end[4] = 1.40;
    assert_eq!(syl.len(), at.len(), "{:?}", syl.iter().map(|s| &s.text).collect::<Vec<_>>());
    syl.into_iter().zip(at.iter().zip(end)).map(|(syl, (&at, end))| SpokenSyllable { syl, at, end }).collect()
}

/// a contour every 10 ms: a fall over the statement, a rise and fall over the question (Hz)
fn glide() -> Contour {
    let v = (0..300)
        .map(|i| {
            let t = i as f64 * 0.01;
            let st = if t < 1.5 { 4.0 - 5.0 * (t - 0.4) } else { 1.0 + 6.0 * (1.0 - ((t - 2.2) / 0.6).powi(2)).max(0.0) };
            110.0 * 2f64.powf(st / 12.0)
        })
        .collect();
    Contour { t0: 0.0, hop: 0.01, v }
}

fn options() -> SpokenOptions {
    SpokenOptions { body: BodyMix::MALE, language: Some(Language::Finnish), f0: glide(), level: Contour::default(), pause: None }
}

#[test]
fn vowels_start_where_the_recording_says() {
    let syls = syllables();
    let plan = plan_spoken(&syls, &options());
    let vowels: Vec<_> = plan.segments.iter().filter(|s| s.kind == "vowel").collect();
    // each syllable's first vowel segment (a diphthong is two)
    let mut k = 0;
    let mut last_t1 = -1.0;
    for v in &vowels {
        if (v.t0 - last_t1).abs() < 1e-9 {
            last_t1 = v.t1; // the second part of a diphthong
            continue;
        }
        assert!((v.t0 - syls[k].at).abs() < 1e-6, "syllable {} ({}) vowel at {:.3}, asked {:.3}", k, syls[k].syl.text, v.t0, syls[k].at);
        last_t1 = v.t1;
        k += 1;
    }
    assert_eq!(k, syls.len());
    // the pause after "ta," splits the speech into two breath groups
    let breaths = plan.gestures.iter().filter(|g| g.label_str() == "breath").count();
    assert_eq!(breaths, 2);
    assert!(plan.end > 2.7 && plan.end < 2.9, "end {}", plan.end);
}

#[test]
fn the_pitch_is_the_recordings_not_the_rules() {
    let o = options();
    let plan = plan_spoken(&syllables(), &o);
    assert!(plan.gestures.iter().filter(|g| g.label_str() == "pitch").all(|g| g.strength == 6.0), "a rule pitch gesture survived");
    let mut score = GestureScore::new();
    score.add_all(&plan.gestures);
    for &t in &[0.45, 0.9, 1.2, 1.85, 2.2, 2.6] {
        let got = score.blend(ControlKey::F0, t).value;
        let want = o.f0.at(t).unwrap();
        assert!((got / want - 1.0).abs() < 0.02, "at {t}: {got:.1} Hz, the contour {want:.1} Hz");
    }
}

#[test]
fn the_level_contour_drives_the_breath() {
    let mut o = options();
    o.level = Contour { t0: 0.0, hop: 0.01, v: (0..300).map(|i| if i < 100 { 1.0 } else { 0.4 }).collect() };
    let plan = plan_spoken(&syllables(), &o);
    let mut score = GestureScore::new();
    score.add_all(&plan.gestures);
    let loud = score.blend(ControlKey::BREATH, 0.6).value;
    let soft = score.blend(ControlKey::BREATH, 2.0).value;
    assert!(loud > 0.95 && soft < 0.6, "breath {loud:.2} loud, {soft:.2} soft");
}

#[test]
fn a_contour_holds_across_unvoiced_stretches() {
    let c = Contour { t0: 0.0, hop: 0.1, v: vec![0.0, 100.0, 0.0, 0.0, 200.0, 0.0] };
    assert_eq!(c.at(0.0), Some(100.0)); // before the first known point: that point
    assert_eq!(c.at(0.1), Some(100.0));
    assert!((c.at(0.25).unwrap() - 150.0).abs() < 1e-9); // between 0.1 s and 0.4 s: linear
    assert_eq!(c.at(0.5), Some(200.0)); // after the last: that point
    assert_eq!(Contour { t0: 0.0, hop: 0.1, v: vec![0.0; 4] }.at(0.2), None);
}

#[test]
fn the_rendered_pitch_follows_the_glide() {
    let o = options();
    let syls = syllables();
    let plan = plan_spoken(&syls, &o);
    let fs = 48000.0;
    let mut v = HumanVoice::new(fs, BODY_MALE, 2);
    v.set_source(&SourcePatch::f0(o.f0.at(syls[0].at).unwrap()));
    v.schedule(&plan.gestures);
    let n = (fs * (plan.end + 0.2)) as usize;
    let mut out = vec![0f32; n];
    for b in out.chunks_mut(128) {
        v.render(b);
    }
    // the middle of each vowel: the tracked pitch against the contour
    let mut errs = Vec::new();
    for s in plan.segments.iter().filter(|s| s.kind == "vowel" && s.t1 - s.t0 > 0.06) {
        let mid = (s.t0 + s.t1) / 2.0;
        let a = ((mid - 0.02) * fs) as usize;
        let frame: Vec<f64> = out[a..a + (0.04 * fs) as usize].iter().map(|&x| x as f64).collect();
        let p = yin_pitch(&frame, fs, YinOpts { min_f0: Some(60.0), max_f0: Some(300.0), threshold: Some(0.2) });
        if p.f0 > 0.0 {
            errs.push((12.0 * (p.f0 / o.f0.at(mid).unwrap()).log2()).abs());
        }
    }
    assert!(errs.len() >= 6, "only {} vowels voiced", errs.len());
    errs.sort_by(f64::total_cmp);
    let median = errs[errs.len() / 2];
    assert!(median < 0.5, "median pitch error {median:.2} semitones ({errs:.2?})");
}
