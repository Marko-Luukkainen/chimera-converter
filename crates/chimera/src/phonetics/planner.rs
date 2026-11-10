//! Segment sequence → gestural score. Timing and phonation are articulatory: aspiration is a
//! glottal opening gesture peaking at the release (VOT emerges), nasality is velum lowering with
//! anticipation, coarticulation comes from overlapping vowel gestures beneath consonant gestures.
//!
//! The planners allocate and run off the audio thread. [`oral_gestures_into`] (used by the beat
//! sequencer) builds into a caller's `Vec` and allocates nothing once it has capacity.

use super::durations::{SegInfo, finnish_durations, klatt_durations};
use super::inventory::{FI_R_X, Glottal, Manner, PhonemeDef, Voicing, alveolar_body, dental_stop, fi_r_heights, phoneme};
use super::{Intonation, Language, Plan, PlannedSegment, Segment};
use crate::anatomy::human::{ArticKey, ArticPatch, BodyMix, BodyName, TractModel};
use crate::control::score::{ControlKey, Gesture, Targets};
use crate::math::{js_max, js_min, js_round};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::OnceLock;

/// label of the end-of-breath-group abduction (a live note can drop it when the next one starts)
pub const EXHALE_LABEL: &str = "exhale";

/// when a sung phrase's breath reaches full drive, after the plan start (its first segment starts at 0.06)
const BREATH_SUNG_AT: f64 = 0.06;

const VOWEL_KEYS: [ArticKey; 9] = [ArticKey::TbX, ArticKey::TbY, ArticKey::Jaw, ArticKey::LipAp, ArticKey::LipProt, ArticKey::LipWidth, ArticKey::Root, ArticKey::Larynx, ArticKey::TtCurl];

/// One calibrated vowel of `vowelTargets.generated.json`.
#[derive(Clone, Debug, Deserialize)]
pub struct VowelTarget {
    pub artic: ArticPatch,
    #[serde(default)]
    pub formants: Vec<f64>,
}

/// body name → IPA → calibrated vowel
pub type VowelTable = BTreeMap<String, BTreeMap<String, VowelTarget>>;

/// The calibrated vowel table (parsed once).
pub fn vowel_table() -> &'static VowelTable {
    static T: OnceLock<VowelTable> = OnceLock::new();
    T.get_or_init(|| serde_json::from_str(include_str!("vowelTargets.generated.json")).expect("vowelTargets.generated.json"))
}

/// The Finnish vowels calibrated to Finnish references (`vowel_data::FI_VOWELS`; parsed once).
/// A Finnish plan takes a vowel from here first and from [`vowel_table`] otherwise.
pub fn fi_vowel_table() -> &'static VowelTable {
    static T: OnceLock<VowelTable> = OnceLock::new();
    T.get_or_init(|| serde_json::from_str(include_str!("vowelTargets.fi.generated.json")).expect("vowelTargets.fi.generated.json"))
}

/// The vowels calibrated for the MRI contour anatomy (`chimera calibrate vowels --contour`).
pub fn contour_vowel_table() -> &'static VowelTable {
    static T: OnceLock<VowelTable> = OnceLock::new();
    T.get_or_init(|| serde_json::from_str(include_str!("vowelTargets.contour.generated.json")).expect("vowelTargets.contour.generated.json"))
}

/// The Finnish vowels calibrated for the MRI contour anatomy (`--fi --contour`).
pub fn contour_fi_vowel_table() -> &'static VowelTable {
    static T: OnceLock<VowelTable> = OnceLock::new();
    T.get_or_init(|| serde_json::from_str(include_str!("vowelTargets.fi.contour.generated.json")).expect("vowelTargets.fi.contour.generated.json"))
}

/// Diphthongs and r-coloured vowels expand to vowel sequences. American /eɪ oʊ/ glide toward
/// [i u] (Hillenbrand et al. 1995: /e/ F2 rises ~150 Hz, /o/ F1 falls with F2 steady); with
/// [ɪ ʊ] as targets they barely moved (/e/ and /ɪ/ share F2) and sounded like the steady
/// [eː oː] of Indian English. The other offglides undershoot toward [ɪ ʊ].
pub fn expand(ipa: &str) -> Option<&'static [&'static str]> {
    Some(match ipa {
        "aɪ" => &["a", "ɪ"],
        "aʊ" => &["a", "ʊ"],
        "ɔɪ" => &["ɔ", "ɪ"],
        "eɪ" => &["e", "i"],
        "oʊ" => &["o", "u"],
        "ɚ" => &["ɝ"],
        _ => return finnish_diphthong(ipa),
    })
}

/// The 18 Finnish diphthongs (the Finnish G2P emits each as one segment). Unlike the American
/// offglides they aim at full [i u y] targets, and the opening ones (ie uo yø) glide from a close
/// vowel to a mid one; the overlapping vowel gestures supply the undershoot of running speech.
fn finnish_diphthong(ipa: &str) -> Option<&'static [&'static str]> {
    Some(match ipa {
        "ɑi" => &["ɑ", "i"],
        "ei" => &["e", "i"],
        "oi" => &["o", "i"],
        "ui" => &["u", "i"],
        "yi" => &["y", "i"],
        "æi" => &["æ", "i"],
        "øi" => &["ø", "i"],
        "ɑu" => &["ɑ", "u"],
        "eu" => &["e", "u"],
        "iu" => &["i", "u"],
        "ou" => &["o", "u"],
        "ey" => &["e", "y"],
        "iy" => &["i", "y"],
        "æy" => &["æ", "y"],
        "øy" => &["ø", "y"],
        "ie" => &["i", "e"],
        "uo" => &["u", "o"],
        "yø" => &["y", "ø"],
        _ => return None,
    })
}

/// The two vowel targets of a diphthong ("aɪ" → ("a", "ɪ")), or None.
pub fn diphthong_parts(ipa: &str) -> Option<(&'static str, &'static str)> {
    match expand(ipa) {
        Some(p) if p.len() == 2 => Some((p[0], p[1])),
        _ => None,
    }
}

pub fn is_vowel(ipa: &str, body: BodyMix) -> bool {
    let t = vowel_table();
    body.weights().iter().any(|(b, w)| *w > 0.0 && t.get(b.cal_name()).is_some_and(|t| t.contains_key(ipa))) || expand(ipa).is_some()
}

/// The calibrated articulation of a vowel for a body: between presets, the presets' calibrated
/// articulations blended by the body's weights. The contour anatomy takes its own calibration
/// first, the classic one where it has none.
pub fn vowel_artic(ipa: &str, body: BodyMix) -> Option<ArticPatch> {
    if body.model == TractModel::Contour
        && let Some(v) = table_vowel_artic(contour_vowel_table(), ipa, body)
    {
        return Some(v);
    }
    table_vowel_artic(vowel_table(), ipa, body)
}

/// [`vowel_artic`] for a language: a Finnish vowel calibrated to Finnish references when the
/// Finnish table has it.
pub fn vowel_artic_in(ipa: &str, body: BodyMix, language: Language) -> Option<ArticPatch> {
    if language == Language::Finnish {
        let fi = if body.model == TractModel::Contour { contour_fi_vowel_table() } else { fi_vowel_table() };
        if let Some(v) = table_vowel_artic(fi, ipa, body) {
            return Some(v);
        }
    }
    vowel_artic(ipa, body)
}

fn table_vowel_artic(t: &VowelTable, ipa: &str, body: BodyMix) -> Option<ArticPatch> {
    if let Some(b) = body.preset() {
        return preset_vowel_artic(t, ipa, b);
    }
    let w = body.weights();
    let mut parts = [(0.0, ArticPatch::default()); 4];
    for (i, (b, wi)) in w.iter().enumerate() {
        if *wi > 0.0 {
            parts[i] = (*wi, preset_vowel_artic(t, ipa, *b)?);
        }
    }
    Some(ArticPatch::blend(&parts))
}

fn preset_vowel_artic(t: &VowelTable, ipa: &str, body: BodyName) -> Option<ArticPatch> {
    let v = t.get(body.cal_name()).and_then(|b| b.get(ipa)).or_else(|| t.get("male").and_then(|m| m.get(ipa)))?;
    let mut out = ArticPatch::default();
    for k in VOWEL_KEYS {
        if let Some(x) = v.artic.get(k) {
            out.set(k, x);
        }
    }
    // a rhotic's tip is raised and curled back, not resting behind the teeth: without its
    // calibrated position the tip stayed down and /ɝ/'s F3 sat ~15–20 % high (weakly rhotic)
    if v.artic.get(ArticKey::TtCurl).unwrap_or(0.0) > 0.05 {
        if let Some(x) = v.artic.get(ArticKey::TtX) {
            out.set(ArticKey::TtX, x);
        }
        if let Some(x) = v.artic.get(ArticKey::TtY) {
            out.set(ArticKey::TtY, x);
        }
    }
    Some(out)
}

/// Parse the vowel and consonant tables now (so nothing initialises lazily on the audio thread).
pub fn init() {
    vowel_table();
    fi_vowel_table();
    contour_vowel_table();
    contour_fi_vowel_table();
    super::inventory::init();
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PlanOptions {
    pub body: BodyMix,
    /// voice-clock start time (s)
    pub t0: f64,
    /// speaking-rate multiplier (>1 = faster)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rate: Option<f64>,
    /// baseline pitch (Hz)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub f0: Option<f64>,
    /// "statement" (final fall) or "question" (final rise)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub intonation: Option<Intonation>,
    /// pitch excursion for stressed syllables (fraction)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub accent: Option<f64>,
    /// the last segment is held open-ended (a sung note): no end-of-breath release
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub open_end: Option<bool>,
    /// a sung phrase (`plan_song`): consonants given a pitch hold it, and pitch ramps shrink to
    /// fit short notes. Speech and live notes leave it unset.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sung: Option<bool>,
    /// the language's duration rules, aspiration and intonation ("en" when unset)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub language: Option<Language>,
}

/// JS truthiness of an optional number (`if (s.f0)`: 0 and NaN are false).
#[inline]
pub(crate) fn truthy(x: Option<f64>) -> bool {
    matches!(x, Some(v) if v != 0.0 && !v.is_nan())
}

/// `Partial<HumanArtic>` as gesture targets
#[inline]
pub(crate) fn artic_targets(p: &ArticPatch) -> Targets {
    let mut t = Targets::default();
    for (k, x) in p.iter() {
        t.set(k, x);
    }
    t
}

#[inline]
fn one(k: impl Into<ControlKey>, x: f64) -> Targets {
    Targets::default().with(k, x)
}

/// A planner segment: the input segment plus what the planner attaches to it.
struct Seg<'a> {
    ipa: &'a str,
    dur: Option<f64>,
    stress: Option<u8>,
    f0: Option<f64>,
    def: Option<PhonemeDef>,
    vowel: Option<ArticPatch>,
    glide_from: bool,
}

#[derive(Clone, Copy)]
struct Span {
    t0: f64,
    t1: f64,
}

pub fn plan_utterance(input: &[Segment], o: &PlanOptions) -> Plan {
    let rate = o.rate.unwrap_or(1.0);
    let body = o.body;
    let finnish = o.language == Some(Language::Finnish);
    // durations by the language's rules (Klatt's for English), on whole segments (diphthongs
    // before they are split)
    let seg_info = |s: &Segment| {
        if is_vowel(&s.ipa, body) {
            return SegInfo { vowel: true, ..Default::default() };
        }
        let d = phoneme(&s.ipa, body);
        SegInfo { vowel: false, manner: d.map(|d| d.manner), voiced: Some(d.is_some_and(|d| d.voicing == Voicing::Voiced)), dur: d.map(|d| d.dur) }
    };
    let durs = if finnish { finnish_durations(input, seg_info) } else { klatt_durations(input, seg_info) };
    // expand diphthongs into two vowel targets sharing the duration
    let mut segs: Vec<Seg> = Vec::with_capacity(input.len() + 4);
    for (si, s) in input.iter().enumerate() {
        if let Some(parts) = expand(&s.ipa) {
            let base = durs[si];
            for (i, p) in parts.iter().enumerate() {
                let dur = if parts.len() > 1 { base * (if i == 0 { 0.55 } else { 0.45 }) } else { base };
                segs.push(Seg { ipa: p, dur: Some(dur), stress: s.stress, f0: s.f0, def: None, vowel: None, glide_from: i > 0 });
            }
        } else {
            segs.push(Seg { ipa: &s.ipa, dur: Some(durs[si]), stress: s.stress, f0: s.f0, def: None, vowel: None, glide_from: false });
        }
    }
    let language = o.language.unwrap_or_default();
    for s in segs.iter_mut() {
        let v = vowel_artic_in(s.ipa, body, language);
        if v.is_some() {
            s.vowel = v;
        } else {
            s.def = phoneme(s.ipa, body);
            // Finnish /t/ is dental
            if finnish && s.ipa == "t" {
                s.def = s.def.map(dental_stop);
            }
        }
    }
    let mut gestures: Vec<Gesture> = Vec::new();
    let mut planned: Vec<PlannedSegment> = Vec::with_capacity(segs.len());
    let mut t = o.t0 + 0.06; // breath onset lead
    let mut times: Vec<Span> = Vec::with_capacity(segs.len());
    for s in &segs {
        let mut d = if let Some(d) = s.dur {
            d
        } else if s.vowel.is_some() {
            if s.stress == Some(1) {
                0.17
            } else if s.stress == Some(2) {
                0.13
            } else {
                0.095
            }
        } else {
            s.def.map_or(0.08, |d| d.dur)
        };
        // final lengthening on the last syllable rhyme
        d /= rate;
        times.push(Span { t0: t, t1: t + d });
        t += d;
    }
    let end = t;
    // ---- vowel gestures: overlap neighbours so the tongue travels vowel-to-vowel
    let v_idx: Vec<usize> = segs.iter().enumerate().filter(|(_, s)| s.vowel.is_some()).map(|(i, _)| i).collect();
    for (n, &i) in v_idx.iter().enumerate() {
        let prev = if n > 0 { times[v_idx[n - 1]].t1 } else { times[i].t0 - 0.08 };
        let next = if n < v_idx.len() - 1 { times[v_idx[n + 1]].t0 } else { times[i].t1 + 0.08 };
        // vowel-to-vowel through the consonant (Öhman): the previous vowel lets go early in the gap
        // and the next one's target ramps in over most of it, so the tongue body is already near
        // the next vowel at the release and the transitions carry the consonant's place
        let r_in = js_max(0.03, 0.75 * (times[i].t0 - prev)) + 0.01;
        let r_out = js_max(0.03, 0.4 * (next - times[i].t1)) + 0.01;
        gestures.push(Gesture::new(times[i].t0, times[i].t1, r_in, r_out, 1.0, artic_targets(segs[i].vowel.as_ref().unwrap())).label(segs[i].ipa));
    }
    // utterance-initial/final consonants: lend them the nearest vowel's body posture
    // ---- consonant gestures
    for (i, s) in segs.iter().enumerate() {
        let Span { t0, t1 } = times[i];
        let dur = t1 - t0;
        planned.push(PlannedSegment {
            ipa: s.ipa.to_string(),
            t0,
            t1,
            stress: if s.vowel.is_some() { Some(s.stress.unwrap_or(0)) } else { None },
            kind: if s.vowel.is_some() { "vowel".to_string() } else { s.def.map_or("?", |d| d.manner.as_str()).to_string() },
        });
        let Some(def) = s.def.as_ref() else { continue };
        let next_vowel = i < segs.len() - 1 && segs[i + 1].vowel.is_some();
        let prev_seg = if i > 0 { Some(&segs[i - 1]) } else { None };
        // Finnish: a consonant after a short vowel approaches in proportion to the vowel's length
        // (and after /r/, whose voiced contacts the dorsum's approach would otherwise smother:
        // in "perkele" the /k/ narrowed the tract under the trill and devoiced two thirds of it)
        let ramp_scale = match prev_seg {
            Some(p) if finnish && (p.vowel.is_some() || p.def.is_some_and(|d| d.manner == Manner::Trill)) => js_min(1.0, js_max(FI_RAMP_MIN, (times[i - 1].t1 - times[i - 1].t0) / FI_RAMP_FULL_VOWEL)),
            _ => 1.0,
        };
        let alveolar_tb = alveolar_body(body);
        let mut add_oral = |tg: &ArticPatch, a: f64, b: f64, speed: f64, label: &str| oral_gestures_ramped(def, tg, a, b, speed, label, ramp_scale, alveolar_tb, &mut gestures);
        match def.manner {
            // a stop that closes behind another stop's closure, its articulator already placed by
            // the segment before that (the tip raised for /ɹ/ in "sharp tree"), reaches contact
            // sooner than from a vowel: with the usual lead it sealed ~20 ms before the front
            // closure opened, and the tongue then pumped the air shut between the two closures
            // The delay leaves the closure 30 ms before its release (its 10 ms minimum hold and
            // its ~20 ms early release), so a short sung stop isn't pushed past its own end.
            Manner::Stop if pre_placed_behind_closure(&segs, i) => add_oral(&def.targets, t0 + js_min(PLACED_CLOSURE_DELAY, js_max(0.0, dur - 0.03)), t1, 1.55, def.ipa),
            // Finnish: the articulator is still near from the consonant before a short vowel
            Manner::Stop | Manner::Nasal if finnish && fi_preplaced(&segs, &times, i) => {
                // a close vowel leaves the articulator nearer: the jaw opens less beneath it
                let jaw = segs[i - 1].vowel.as_ref().and_then(|v| v.get(ArticKey::Jaw)).unwrap_or(1.0);
                let d = js_min(FI_PRESET_DELAY * js_min(1.0, js_max(0.0, (FI_PRESET_OPEN_JAW - jaw) / (FI_PRESET_OPEN_JAW - 0.4))), js_max(0.0, dur - 0.03));
                add_oral(&def.targets, t0 + d, t1, 1.55, def.ipa)
            }
            Manner::Stop | Manner::Nasal => add_oral(&def.targets, t0, t1, 1.55, def.ipa),
            Manner::Tap => add_oral(&def.targets, t0, t1, 2.8, def.ipa),
            Manner::Trill if finnish => {
                // the open time a following consonant needs before it starts forming: a fricative
                // forms its constriction FI_FRIC_ORAL_LEAD early, so it needs more
                let tail = match segs.get(i + 1).and_then(|n| n.def) {
                    Some(n) if n.manner == Manner::Fricative => FI_R_TAIL + FI_FRIC_ORAL_LEAD,
                    Some(_) => FI_R_TAIL,
                    None => 0.0,
                };
                finnish_r_gestures(def, body, t0, t1, tail, &mut gestures)
            }
            Manner::Trill => {
                // driven trill: rapid alternation of near-closure and release at ~26 Hz
                let n = js_max(2.0, js_round(dur * 26.0));
                let mut k = 0.0;
                while k < n {
                    let a = t0 + (k / n) * dur;
                    add_oral(&def.targets, a, a + 0.35 / 26.0, 3.2, def.ipa);
                    k += 1.0;
                }
            }
            Manner::Affricate => {
                let split = t0 + dur * 0.55;
                add_oral(&def.targets, t0, split, 2.0, def.ipa);
                let rel = def.release.and_then(|r| phoneme(r, body));
                if let Some(rel) = rel {
                    add_oral(&rel.targets, split + 0.008, t1, 1.4, def.ipa);
                }
            }
            // Finnish fricatives form their constriction before the segment starts and let it go
            // just before its end
            Manner::Fricative if finnish => add_oral(&def.targets, t0 - FI_FRIC_ORAL_LEAD, t1 - FI_FRIC_RELEASE_LEAD, FI_FRIC_SPEED, def.ipa),
            Manner::Fricative | Manner::Approximant | Manner::Lateral => add_oral(&def.targets, t0, t1, 1.3, def.ipa),
            Manner::Glottal | Manner::Vowel => {}
        }
        // nasality: the velum lowers in anticipation (into the preceding vowel, as in English) and
        // seals again by the end of the nasal; 0.45 cm² is ample for the murmur
        if def.nasal == Some(true) {
            gestures.push(Gesture::new(t0 - 0.02, t1 - 0.02, 0.05, 0.03, 4.0, one(ArticKey::Velum, 0.45)).label("velum"));
        }
        // phonation
        let k2 = 1.0; // abduction is body-scaled in the voice
        if def.glottal == Some(Glottal::Open) {
            gestures.push(Gesture::new(t0 - 0.01, t1, 0.03, 0.035, 5.0, one(ControlKey::ABDUCTION, 0.33 * k2)).label("h"));
        } else if def.glottal == Some(Glottal::Breathy) {
            gestures.push(Gesture::new(t0, t1, 0.03, 0.03, 5.0, one(ControlKey::ABDUCTION, 0.1 * k2)).label("ɦ"));
        } else if def.glottal == Some(Glottal::Stop) {
            gestures.push(Gesture::new(t0, t1, 0.012, 0.015, 8.0, one(ControlKey::CLOSURE, 1.0)).label("ʔ"));
        } else if def.voicing == Voicing::Voiceless && finnish && def.manner == Manner::Stop {
            // the glottis closes again by the release, so voicing starts 10–25 ms after it
            gestures.push(Gesture::new(t0 + 0.25 * dur, t1 - fi_stop_glottal_end(def.place), 0.035, FI_STOP_GLOTTAL_RAMP, 6.0, one(ControlKey::ABDUCTION, FI_STOP_ABDUCTION)).label("aspiration"));
        } else if def.voicing == Voicing::Voiceless && finnish {
            // the glottis opens with the fricative and closes before its end, so a short vowel on
            // either side keeps its voicing
            gestures.push(Gesture::new(t0 - FI_FRIC_GLOTTAL_LEAD, t1 - FI_FRIC_GLOTTAL_END, 0.02, 0.02, 6.0, one(ControlKey::ABDUCTION, 0.3)).label("voiceless"));
        } else if def.voicing == Voicing::Voiceless {
            if def.manner == Manner::Stop || def.manner == Manner::Affricate {
                // aspirated when syllable-initial before a vowel and not after /s/ (English-like);
                // Finnish /p t k/ are unaspirated everywhere (short-lag VOT, ~10–20 ms)
                let aspirated = !finnish && next_vowel && !prev_seg.is_some_and(|p| p.ipa == "s");
                let vot = if aspirated { 0.05 / rate } else { 0.012 };
                gestures.push(Gesture::new(t0 + 0.25 * dur, t1 + vot * 0.4, 0.035, if aspirated { 0.045 } else { 0.02 }, 6.0, one(ControlKey::ABDUCTION, if aspirated { 0.36 } else { 0.22 })).label("aspiration"));
            } else {
                gestures.push(Gesture::new(t0 - 0.015, t1 + 0.005, 0.03, 0.03, 6.0, one(ControlKey::ABDUCTION, 0.3)).label("voiceless"));
            }
        } else if def.manner == Manner::Fricative {
            gestures.push(Gesture::new(t0, t1, 0.03, 0.03, 3.0, one(ControlKey::ABDUCTION, 0.035)).label("voiced frication"));
        }
    }
    let open_end = o.open_end == Some(true);
    let sung = o.sung == Some(true);
    // ---- breath: on through the utterance. A sung phrase's onset is planned (its first vowel
    // lands on the beat), so a singer times the breath to it: the pressure reaches full drive as
    // the first segment starts, and builds into adducted folds or behind the first constriction
    // rather than voicing ahead of the note. Speech and live notes keep their 20 ms lead.
    let breath_at = if sung { BREATH_SUNG_AT } else { 0.04 };
    gestures.push(Gesture::new(o.t0 + breath_at, end, 0.04, if open_end { 0.07 } else { 0.05 }, 1.0, one(ControlKey::BREATH, 1.0)).label("breath"));
    // ---- end of the breath group: the folds part as the breath stops, so a final obstruent is
    // released into silence instead of into an added vowel ("cat-uh"). After a vowel or sonorant
    // they part once the pressure has fallen, so the voice fades out instead of ending in an [h].
    if !open_end {
        let last = segs.last();
        let sonorant = last.is_some_and(|l| l.vowel.is_some()) || last.and_then(|l| l.def).is_some_and(|d| matches!(d.manner, Manner::Nasal | Manner::Approximant | Manner::Lateral | Manner::Tap | Manner::Trill));
        let at = end + if sonorant { 0.045 } else { 0.015 };
        gestures.push(Gesture::new(at, end + 0.1, 0.03, 0.06, 6.0, one(ControlKey::ABDUCTION, 0.22)).label(EXHALE_LABEL));
    }
    // ---- intonation: pitch targets on vowels
    let f0 = o.f0.unwrap_or(110.0);
    // Finnish: each stressed word-initial syllable gets a modest rise-fall, with no outsized
    // nuclear accent, and a question is marked by -ko/-kö or a question word rather than a rise
    let accent = o.accent.unwrap_or(if finnish { 0.09 } else { 0.14 });
    let nuclear_gain = if finnish { 1.3 } else { 1.8 };
    let intonation = match o.intonation {
        Some(Intonation::Question) if finnish => Some(Intonation::Statement),
        x => x,
    };
    let total = js_max(0.2, end - o.t0);
    // the nuclear accent: the phrase's last primary-stressed vowel, a bigger excursion that falls
    // (statements) into the final low; earlier accents are smaller (a "hat" pattern)
    let mut nuclear: isize = -1;
    for &i in &v_idx {
        if segs[i].stress == Some(1) && !segs[i].glide_from {
            nuclear = i as isize;
        }
    }
    for (n, &i) in v_idx.iter().enumerate() {
        let s = &segs[i];
        let Span { t0, t1 } = times[i];
        // pitch holds through the consonants up to the next vowel (instead of sagging to the base)
        let hold = if n < v_idx.len() - 1 { js_max(t1, times[v_idx[n + 1]].t0 - 0.03) } else { t1 };
        let mut target: f64;
        let has_f0 = truthy(s.f0);
        if has_f0 {
            target = s.f0.unwrap();
        } else {
            let prog = (t0 - o.t0) / total;
            let decl = 1.0 - 0.1 * prog;
            let is_nuclear = i as isize == nuclear;
            let acc = if s.stress == Some(1) {
                1.0 + (if is_nuclear { accent * nuclear_gain } else { accent })
            } else if s.stress == Some(2) {
                1.0 + accent * 0.5
            } else {
                1.0
            };
            target = f0 * decl * acc;
            let last = n == v_idx.len() - 1;
            if last && intonation == Some(Intonation::Question) {
                target = f0 * 1.35;
            }
            if last && intonation.unwrap_or(Intonation::Statement) == Intonation::Statement {
                if is_nuclear && t1 - t0 > 0.08 {
                    // accent peak early in the vowel, then the fall within it
                    gestures.push(Gesture::new(t0, t0 + 0.35 * (t1 - t0), 0.05, 0.05, 1.0, one(ControlKey::F0, target)).label("pitch"));
                    gestures.push(Gesture::new(t0 + 0.55 * (t1 - t0), t1, 0.06, 0.06, 1.0, one(ControlKey::F0, f0 * 0.82)).label("pitch"));
                    continue;
                }
                target = f0 * 0.82;
            }
        }
        let r = if has_f0 && sung { pitch_ramp(t1 - t0) } else { 0.06 };
        gestures.push(Gesture::new(t0, if has_f0 { t1 } else { hold }, r, r, if has_f0 { 6.0 } else { 1.0 }, one(ControlKey::F0, target)).label("pitch"));
    }
    // sung: a consonant given its note's pitch holds it, so the pitch moves during an onset
    // consonant and has arrived when the vowel starts
    for (i, s) in segs.iter().enumerate() {
        if sung && s.vowel.is_none() && truthy(s.f0) {
            let Span { t0, t1 } = times[i];
            let r = pitch_ramp(t1 - t0);
            gestures.push(Gesture::new(t0, t1, r, r, 6.0, one(ControlKey::F0, s.f0.unwrap())).label("pitch"));
        }
    }
    Plan { gestures, segments: planned, end }
}

/// Finnish voiceless stops: when the glottal opening ends before the release (s), and how fast
/// it closes. Finnish /p t k/ are unaspirated with a weak burst: VOT word-initially 9 / 11 /
/// 20 ms, medially 11 / 16 / 25 ms (Suomi 1980, in Suomi et al. 2008 §3.2).
fn fi_stop_glottal_end(place: &str) -> f64 {
    match place {
        "bilabial" => 0.012,
        "velar" => 0.0,
        _ => 0.008,
    }
}
const FI_STOP_GLOTTAL_RAMP: f64 = 0.015;
const FI_STOP_ABDUCTION: f64 = 0.22;
/// Finnish voiceless fricatives: the glottal opening starts this long before the segment and
/// ends this long before its end (s), so a short vowel next to /s/ keeps its voicing.
const FI_FRIC_GLOTTAL_LEAD: f64 = 0.0;
const FI_FRIC_GLOTTAL_END: f64 = 0.012;
/// Finnish fricatives: the constriction gesture starts this much earlier (s) and moves at this
/// speed, so the constriction has formed when the segment starts.
const FI_FRIC_ORAL_LEAD: f64 = 0.03;
const FI_FRIC_SPEED: f64 = 2.0;

/// Finnish fricatives let go of their constriction this long before their end (s): the release
/// ran 16 ms into a following short vowel ("satama").
const FI_FRIC_RELEASE_LEAD: f64 = 0.01;
/// How much later a Finnish closure is aimed when its articulator is still near from the
/// consonant before a short vowel (s): in "satama" the /t/ sealed 30 ms early, leaving the /a/
/// open for ~10 ms and voicing into the closure.
const FI_PRESET_DELAY: f64 = 0.025;
/// The jaw opening (template cm) at which a vowel lets the articulator drop fully, so the delay
/// is zero; it grows to FI_PRESET_DELAY at a close vowel's jaw (0.4).
const FI_PRESET_OPEN_JAW: f64 = 1.8;
/// A vowel shorter than this (s) leaves a consonant's articulator near for the next one.
const FI_PRESET_VOWEL: f64 = 0.12;

/// Whether consonant `i` comes after a short vowel whose preceding consonant used the same
/// articulators (s·a·t, t·i·t, n·a·t: the tip has not dropped far in 60–90 ms).
fn fi_preplaced(segs: &[Seg], times: &[Span], i: usize) -> bool {
    if i < 2 || segs[i - 1].vowel.is_none() || times[i - 1].t1 - times[i - 1].t0 >= FI_PRESET_VOWEL {
        return false;
    }
    let (Some(def), Some(prev)) = (segs[i].def.as_ref(), segs[i - 2].def.as_ref()) else { return false };
    def.dominant.iter().any(|k| prev.dominant.contains(k))
}

/// A consonant after a vowel shorter than this (s) approaches with a proportionally shorter
/// ramp, down to FI_RAMP_MIN of the usual one.
const FI_RAMP_FULL_VOWEL: f64 = 0.12;
const FI_RAMP_MIN: f64 = 0.4;

/// One contact period of the Finnish /r/ (s): ~29 Hz, inside the 25–35 Hz of measured trills.
pub const FI_R_PERIOD: f64 = 0.034;
/// How long each contact gesture is held (s), and how far ahead of the contact centre it starts.
const FI_R_CONTACT: f64 = 0.012;
const FI_R_LEAD: f64 = 0.015;
/// Tip speed during the /r/: a trill's contacts are aerodynamically driven, far faster than a
/// voluntary tip movement.
const FI_R_SPEED: f64 = 6.0;
/// Open time kept after the last contact when a consonant follows (s). With 18 ms, the second
/// contact of "perkele" fell into a tract the /k/ was already narrowing: the voicing stopped
/// and the release came out as a loud voiceless [h] ("perhkele"); with 40 ms the /r/ before a
/// voiceless stop is one contact and a voiced release, voiced for 70 % of its length.
const FI_R_TAIL: f64 = 0.04;
/// How early the tip starts rising toward the ridge before the /r/ (s).
const FI_R_RAISE: f64 = 0.025;

/// Finnish /r/: brief, light, voiced alveolar contacts, one per [`FI_R_PERIOD`] of the segment
/// (a tap when it is short, a trill of two or more contacts when long), with the tip pulled back
/// to an open position between contacts and after the last, so the voicing carries on through
/// the /r/ and a following closure (/rk/, /rt/) never seals behind a tip still in contact.
/// The generic trill held its contact gestures with 30 ms ramps, so its contacts merged into
/// one long closure: /r/ came out as silence with a click, and in "perkele" the /k/ closure
/// squeezed the air trapped behind the tip into a pop.
/// The tip heights come from [`fi_r_heights`] (the anatomy's own ridge).
fn finnish_r_gestures(def: &PhonemeDef, body: BodyMix, t0: f64, t1: f64, tail: f64, out: &mut Vec<Gesture>) {
    let (open_y, close_y) = fi_r_heights(body);
    let dur = t1 - t0;
    // before a consonant the contacts keep clear of its approach (`tail` of open time), so the
    // tip has let go and the voicing resumed before the next constriction forms; a span too
    // short for the contacts at a trill's rate gets fewer of them ("kirsikka": one before /s/)
    let span = if tail > 0.0 { js_max(0.5 * dur, dur - tail) } else { dur };
    let n = js_max(1.0, js_min(js_round(dur / FI_R_PERIOD), js_round(span / (0.7 * FI_R_PERIOD))));
    let period = span / n;
    let tip = |y: f64| Targets::default().with(ArticKey::TtX, FI_R_X).with(ArticKey::TtY, y);
    // the tip rises toward the ridge during the end of the vowel before, as speakers anticipate a
    // trill; from the vowel's resting tip the first contact fell short (0.05 cm², no seal)
    let open_end = if tail > 0.0 { t0 + span } else { t1 };
    out.push(Gesture::new(t0 - FI_R_RAISE, open_end, FI_R_RAISE, 0.015, 8.0, tip(open_y)).speed(FI_R_SPEED).label(def.ipa));
    let mut k = 0.0;
    while k < n {
        let c = t0 + (k + 0.5) * period;
        out.push(Gesture::new(c - FI_R_LEAD, c - FI_R_LEAD + FI_R_CONTACT, 0.004, 0.004, 40.0, tip(close_y)).speed(FI_R_SPEED).label(def.ipa));
        k += 1.0;
    }
}

/// Front-to-back order of the oral places of articulation.
fn place_rank(place: &str) -> Option<u8> {
    Some(match place {
        "bilabial" => 0,
        "labiodental" => 1,
        "dental" => 2,
        "alveolar" => 3,
        "postalveolar" => 4,
        "retroflex" => 5,
        "palatal" => 6,
        "velar" => 7,
        "uvular" => 8,
        _ => return None,
    })
}

/// How much later a pre-placed closure behind another stop's closure is aimed (s): the time its
/// shorter travel saves, so it seals as the front closure opens.
const PLACED_CLOSURE_DELAY: f64 = 0.025;

/// Whether stop `i` closes behind the closure of the stop before it, with its own articulators
/// already set by the consonant before that one (/t/ in /ɹpt/: the tip is up for the /ɹ/ and
/// stays free during the lip closure; a rhotic vowel raises it too). After any other vowel ("apt",
/// "napkin") the timing is unchanged.
fn pre_placed_behind_closure(segs: &[Seg], i: usize) -> bool {
    let (Some(def), Some(prev)) = (segs[i].def.as_ref(), i.checked_sub(1).and_then(|j| segs[j].def.as_ref())) else { return false };
    if def.manner != Manner::Stop || prev.manner != Manner::Stop || !closes_in_front(prev.place, def.place) || i < 2 {
        return false;
    }
    let before = &segs[i - 2];
    let rhotic = before.vowel.as_ref().filter(|v| v.get(ArticKey::TtCurl).unwrap_or(0.0) > 0.05);
    let Some(tg) = before.def.as_ref().map(|d| &d.targets).or(rhotic) else { return false };
    def.dominant.iter().all(|k| tg.get(*k).is_some())
}

/// Whether a closure at `front` lies in front of one at `back`.
fn closes_in_front(front: &str, back: &str) -> bool {
    matches!((place_rank(front), place_rank(back)), (Some(f), Some(b)) if f < b)
}

/// Ramps of a given pitch (a sung note's) on a segment `dur` long: 60 ms, but at most half the
/// segment. A ramp-in starts before the segment, so in a fast run a full 60 ms would pull the
/// previous vowel off its note for most of its length.
fn pitch_ramp(dur: f64) -> f64 {
    js_min(0.06, js_max(0.008, 0.5 * dur))
}

/// Oral gestures for one consonant constriction held acoustically from `a` to `b` (closure to
/// release): a dominant gesture on the consonant's own articulators and a weak one on the rest.
/// Movement latencies are compensated so the acoustic closure and release land on a and b.
pub fn oral_gestures(def: &PhonemeDef, tg: &ArticPatch, a: f64, b: f64, speed: f64, label: &str, body: BodyMix) -> Vec<Gesture> {
    let mut out = Vec::with_capacity(4);
    oral_gestures_into(def, tg, a, b, speed, label, body, &mut out);
    out
}

/// [`oral_gestures`], appended to `out` (at most four gestures; no allocation when `out` has
/// room for them).
#[allow(clippy::too_many_arguments)]
pub fn oral_gestures_into(def: &PhonemeDef, tg: &ArticPatch, a: f64, b: f64, speed: f64, label: &str, body: BodyMix, out: &mut Vec<Gesture>) {
    oral_gestures_ramped(def, tg, a, b, speed, label, 1.0, alveolar_body(body), out)
}

/// [`oral_gestures_into`] with the dominant gesture's ramp-in scaled by `ramp_scale` (1 for the
/// usual approach). A Finnish short vowel (60–80 ms) between two consonants left no time for the
/// usual 30 ms approach plus latency lead: in "kukka" the /kk/ closure began forming 40 ms
/// before its planned start, and the /u/ was voiced for under a third of its length.
#[allow(clippy::too_many_arguments)]
fn oral_gestures_ramped(def: &PhonemeDef, tg: &ArticPatch, a: f64, b: f64, speed: f64, label: &str, ramp_scale: f64, alveolar_tb: (f64, f64), out: &mut Vec<Gesture>) {
    let mut dom = ArticPatch::default();
    let mut sec = ArticPatch::default();
    for (k, v) in tg.iter() {
        if def.dominant.contains(&k) {
            dom.set(k, v);
        } else {
            sec.set(k, v);
        }
    }
    let is = |k: &ArticKey, a: ArticKey, b: ArticKey, c: ArticKey| *k == a || *k == b || *k == c;
    // the dorsum is heavy: its releases are slower than tip and lip releases
    let body_only = def.dominant.iter().all(|k| is(k, ArticKey::TbX, ArticKey::TbY, ArticKey::Root));
    let sp = if body_only { 1.0 + (speed - 1.0) * 0.35 } else { speed };
    // articulators need ~10–15 ms to climb out of the overshoot (contact) target, so the
    // gesture releases early and the acoustic release lands on the planned boundary:
    // measured movement latencies (closure lag / release lag) per articulator class
    let closing = matches!(def.manner, Manner::Stop | Manner::Nasal | Manner::Affricate);
    let lips_only = def.dominant.iter().all(|k| *k == ArticKey::LipAp || *k == ArticKey::Labiodental);
    let lead = if closing { if body_only { 0.034 } else if lips_only { 0.019 } else { 0.02 } } else { 0.0 };
    // a consonant must own its constriction articulators (Task-Dynamics style): at strength 40
    // the overlapping vowel contributes ~2 %, so closures seal instead of being diluted
    let early = if closing { if body_only { 0.024 } else if lips_only { 0.022 } else { 0.031 } } else { 0.008 };
    if !dom.is_empty() {
        // only the heavy dorsum's approach is shortened: a tip or lip closure with a shorter ramp
        // sealed ~20 ms late ("ata"), while the dorsum's early approach ate a short vowel
        let ramp_in = if body_only { 0.03 * ramp_scale } else { 0.03 };
        out.push(Gesture::new(a - early, js_max(a + 0.01, b - lead), ramp_in, if body_only { 0.03 } else { 0.018 }, 40.0, artic_targets(&dom)).speed(sp).release_hold(0.045).label(label));
    }
    // alveolars front the tongue body during the closure (the alveolar F2 locus, ~1.8 kHz)
    let alveolar = def.place == "alveolar" && tg.get(ArticKey::TbX).is_none() && matches!(def.manner, Manner::Stop | Manner::Nasal | Manner::Fricative | Manner::Affricate | Manner::Tap);
    if alveolar {
        out.push(Gesture::new(a, b, 0.05, 0.05, 1.2, Targets::default().with(ArticKey::TbX, alveolar_tb.0).with(ArticKey::TbY, alveolar_tb.1)).label(label));
    }
    if !sec.is_empty() {
        // a velar's front–back place follows the vowel (fronted /k/ in "key", backed in "caw"):
        // its own tbX only weakly, so the F2 locus moves with the vowel as in natural speech
        let place = if body_only { sec.get(ArticKey::TbX) } else { None };
        if place.is_some() {
            sec.values[ArticKey::TbX.index()] = None;
        }
        if !sec.is_empty() {
            out.push(Gesture::new(a, b, 0.05, 0.05, 2.2, artic_targets(&sec)).label(label));
        }
        if let Some(x) = place {
            out.push(Gesture::new(a, b, 0.05, 0.05, 0.25, one(ArticKey::TbX, x)).label(label));
        }
    }
}

/// One phrase of [`plan_phrases`].
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PhraseInput {
    pub segments: Vec<Segment>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub intonation: Option<Intonation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pause: Option<f64>,
}

/// Plan consecutive phrases (each with its own breath group and intonation) from t0.
/// `o.intonation` is ignored (each phrase brings its own).
pub fn plan_phrases(phrases: &[PhraseInput], o: &PlanOptions) -> Plan {
    let mut all = Plan { gestures: Vec::new(), segments: Vec::new(), end: o.t0 };
    let mut t = o.t0;
    for p in phrases {
        let plan = plan_utterance(&p.segments, &PlanOptions { t0: t, intonation: Some(p.intonation.unwrap_or(Intonation::Statement)), ..o.clone() });
        all.gestures.extend_from_slice(&plan.gestures);
        all.segments.extend(plan.segments);
        t = plan.end + p.pause.unwrap_or(0.25);
        all.end = plan.end;
    }
    all
}
