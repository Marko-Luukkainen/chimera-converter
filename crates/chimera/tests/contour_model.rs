//! The MRI contour anatomy (`anatomy::contour`, `TractModel::Contour`): the switch, the model,
//! its calibrated vowels, its stops and its real-time contract.
use chimera::anatomy::contour::{self, N_LINES, N_PHAR};
use chimera::anatomy::geom::Vec2;
use chimera::anatomy::human::{BODY_CHILD, BODY_FEMALE, BODY_MALE, BodyMix, BodyName, HumanArtic, HumanFrame, HumanVocalTract, NEUTRAL, TractModel};
use chimera::phonetics::planner::{PlanOptions, contour_fi_vowel_table, contour_vowel_table, plan_utterance, vowel_artic, vowel_table};
use chimera::phonetics::{Language, Segment};
use chimera::voice::human_voice::{HumanVoice, SourcePatch};
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

struct Counting;

thread_local! {
    static ALLOCS: Cell<usize> = const { Cell::new(0) };
}

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        ALLOCS.with(|n| n.set(n.get() + 1));
        unsafe { System.alloc(l) }
    }
    unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
        unsafe { System.dealloc(p, l) }
    }
    unsafe fn realloc(&self, p: *mut u8, l: Layout, n: usize) -> *mut u8 {
        ALLOCS.with(|c| c.set(c.get() + 1));
        unsafe { System.realloc(p, l, n) }
    }
}

#[global_allocator]
static A: Counting = Counting;

fn allocs() -> usize {
    ALLOCS.with(|n| n.get())
}

#[test]
fn the_anatomy_is_part_of_the_body_and_classic_files_stay_as_they_were() {
    let b = BodyMix::from("female/contour");
    assert_eq!(b.model, TractModel::Contour);
    assert_eq!(b.nearest(), BodyName::Female);
    assert_eq!(b.body().model, TractModel::Contour);
    let j = serde_json::to_value(b).unwrap();
    assert_eq!(j["model"], "contour");
    assert_eq!(serde_json::from_value::<BodyMix>(j).unwrap(), b);
    // a classic body serializes as before (goldens, saved songs and styles)
    assert_eq!(serde_json::to_string(&BodyMix::FEMALE).unwrap(), r#"{"female":1.0,"child":0.0}"#);
    assert!(!serde_json::to_string(&BODY_FEMALE).unwrap().contains("model"));
    let mix: BodyMix = serde_json::from_str(r#"{"female":0.5,"child":0.25,"model":"contour"}"#).unwrap();
    assert_eq!(mix.body().model, TractModel::Contour);
    assert_eq!(BodyMix::from("male").model, TractModel::Classic);
}

#[test]
fn the_contour_anatomy_has_the_mri_walls_and_keeps_the_classic_incisor() {
    let classic = HumanVocalTract::new(BODY_MALE);
    let mri = HumanVocalTract::new(BODY_MALE.with_model(TractModel::Contour));
    let (pc, pm) = (classic.palate(), mri.palate());
    let close = |a: Vec2, b: Vec2| (a.x - b.x).abs() < 0.02 && (a.y - b.y).abs() < 0.02;
    // the ends are shared: the soft palate hinges at the first point, the teeth and lips sit on the last
    assert!(close(pc[0], pm[0]), "{:?} {:?}", pc[0], pm[0]);
    assert!(close(pc[pc.len() - 1], pm[pm.len() - 1]), "{:?} {:?}", pc[pc.len() - 1], pm[pm.len() - 1]);
    // in between it is the MRI's
    let m = contour::model();
    assert!(m.palate.len() > 10 && m.phar_wall.len() > 10);
    assert!(m.source.contains("10.5281/zenodo.10046815"));
}

#[test]
fn the_contour_tongue_follows_its_guides() {
    let m = contour::model();
    let at = |a: &HumanArtic| {
        let mut p = [Vec2::default(); N_LINES];
        m.tongue(a, &mut p);
        p
    };
    let n = at(&NEUTRAL);
    let up = at(&HumanArtic { tb_y: NEUTRAL.tb_y + 0.5, ..NEUTRAL });
    let fwd = at(&HumanArtic { tb_x: NEUTRAL.tb_x + 0.5, ..NEUTRAL });
    let top = N_PHAR + 9; // the line straight up
    assert!(up[top].y > n[top].y + 0.3, "raising the body raises the dorsum");
    assert!(fwd[N_PHAR].x > n[N_PHAR].x + 0.2, "fronting the body moves its back forward");
    // the tongue is one smooth surface: neighbouring points stay within a few mm of each other
    for i in 1..N_LINES {
        let d = ((n[i].x - n[i - 1].x).powi(2) + (n[i].y - n[i - 1].y).powi(2)).sqrt();
        assert!(d < 0.75, "line {i}: {d:.2} cm from its neighbour");
    }
}

#[test]
fn every_vowel_is_calibrated_for_the_contour_anatomy() {
    let mut bad = Vec::new();
    for (table, name) in [(contour_vowel_table(), "en"), (contour_fi_vowel_table(), "fi")] {
        for body in ["male", "female", "child"] {
            let t = &table[body];
            assert!(t.len() >= 5, "{name} {body}: {} vowels", t.len());
            for (ipa, v) in t {
                // Finnish /u/'s F1 (310 Hz for men) is below what the tract reaches with the lips
                // at full protrusion, in either anatomy (the classic misses it by up to 15 %). The
                // open vowels /a ɑ ɔ/ fall 10-16 % short on F1: the MRI's pharynx is wider than the
                // classic one and the counting it was fitted to has no fully open vowel
                // (the classic misses them by 5-10 %)
                let tol = if name == "fi" && ipa == "u" { 25.0 } else { 17.0 };
                assert!(v.formants.len() >= 3, "{name} {body} {ipa}: only {} resonances", v.formants.len());
                // the recorded errors (F1, F2) are what the fit reached
                let path = format!("{name} {body} {ipa}");
                bad.extend(v_err(name, body, ipa).iter().take(2).filter(|e| e.abs() > tol).map(|e| format!("{path}: {e:.1} %")));
            }
        }
    }
    assert_eq!(bad, Vec::<String>::new());
    // a contour body's plan takes its own table
    let c = vowel_artic("i", BodyMix::from("male/contour")).unwrap();
    let k = vowel_artic("i", BodyMix::MALE).unwrap();
    assert_ne!(c, k);
    assert_eq!(c.get(chimera::anatomy::human::ArticKey::TbY), contour_vowel_table()["male"]["i"].artic.get(chimera::anatomy::human::ArticKey::TbY));
    assert!(vowel_table()["male"].contains_key("i"));
}

/// The table's recorded formant errors (%), read from the generated file.
fn v_err(lang: &str, body: &str, ipa: &str) -> Vec<f64> {
    let text = if lang == "fi" { include_str!("../src/phonetics/vowelTargets.fi.contour.generated.json") } else { include_str!("../src/phonetics/vowelTargets.contour.generated.json") };
    let v: serde_json::Value = serde_json::from_str(text).unwrap();
    v[body][ipa]["err"].as_array().unwrap().iter().map(|e| e.as_f64().unwrap_or(f64::NAN)).collect()
}

/// Every calibrated vowel of every body leaves the tract open, with finite areas.
#[test]
fn contour_vowels_leave_the_tract_open() {
    for (body, b) in [("male", BODY_MALE), ("female", BODY_FEMALE), ("child", BODY_CHILD)] {
        let mut tract = HumanVocalTract::new(b.with_model(TractModel::Contour));
        let mut f = HumanFrame::with_capacity();
        for (ipa, v) in &contour_vowel_table()[body] {
            let a = v.artic.apply_to(&NEUTRAL);
            tract.compute(&a, &mut f);
            let min = f.grid.iter().map(|g| g.area).fold(f64::INFINITY, f64::min);
            assert!(f.grid.iter().all(|g| g.area.is_finite()), "{body} {ipa}");
            assert!(min > 0.05 * b.scale * b.scale, "{body} {ipa}: narrowest {min:.3} cm²");
            assert!(f.length > 10.0 * b.scale && f.length < 22.0 * b.scale, "{body} {ipa}: length {:.1}", f.length);
        }
    }
}

fn segs(ipa: &[&str]) -> Vec<Segment> {
    let mut s: Vec<Segment> = ipa.iter().map(|p| Segment::new(p)).collect();
    s.last_mut().unwrap().word_end = Some(true);
    s
}

/// The stops keep their classic targets (tip, lips and the tongue body for /k/): in the MRI
/// tongue they must still seal.
#[test]
fn contour_stops_seal() {
    for (name, f0) in [("male", 110.0), ("female", 200.0)] {
        let body = format!("{name}/contour");
        for (w, c) in [(["ɑ", "p", "ɑ"], "p"), (["ɑ", "t", "ɑ"], "t"), (["ɑ", "k", "ɑ"], "k"), (["i", "k", "i"], "k")] {
            let plan = plan_utterance(&segs(&w), &PlanOptions { body: body.as_str().into(), t0: 0.05, f0: Some(f0), language: Some(Language::English), ..Default::default() });
            let mut v = HumanVoice::new(48000.0, BodyMix::from(body.as_str()).body(), 2);
            v.set_source(&SourcePatch::f0(f0));
            v.schedule(&plan.gestures);
            let mut out = vec![0f32; (48000.0 * (plan.end + 0.3)) as usize];
            for ch in out.chunks_mut(128) {
                v.render(ch);
            }
            assert!(out.iter().all(|x| x.is_finite()), "{body} {w:?}: non-finite output");
            let rms = |a: f64, b: f64| {
                let (a, b) = ((a * 48000.0) as usize, (b * 48000.0) as usize);
                (out[a..b].iter().map(|x| (*x as f64).powi(2)).sum::<f64>() / (b - a) as f64).sqrt()
            };
            let s = plan.segments.iter().find(|s| s.ipa == c).unwrap();
            let v0 = plan.segments.iter().find(|s| s.kind == "vowel").unwrap();
            let (mid, h) = ((s.t0 + s.t1) / 2.0, (s.t1 - s.t0) * 0.2);
            let db = 20.0 * (rms(mid - h, mid + h) / rms(v0.t0 + 0.01, v0.t1 - 0.01)).log10();
            assert!(db < -30.0, "{body} {w:?}: mid-closure only {db:.1} dB below the vowel");
        }
    }
}

/// The engine's contract: once warm, the contour anatomy computes a frame without allocating.
#[test]
fn the_contour_anatomy_does_not_allocate_once_warm() {
    contour::init();
    let mut tract = HumanVocalTract::new(BODY_FEMALE.with_model(TractModel::Contour));
    let mut f = HumanFrame::with_capacity();
    let postures: Vec<HumanArtic> = contour_vowel_table()["female"].values().map(|v| v.artic.apply_to(&NEUTRAL)).collect();
    for a in &postures {
        tract.compute(a, &mut f);
    }
    let before = allocs();
    for _ in 0..3 {
        for a in &postures {
            tract.compute(a, &mut f);
            tract.compute(&HumanArtic { larynx: 0.8, velum: 1.0, dorsum: 0.5, ..*a }, &mut f);
        }
    }
    assert_eq!(allocs() - before, 0);
}
