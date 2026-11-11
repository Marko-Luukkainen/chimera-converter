//! Speech as it was spoken: syllables at a recording's times, through the speech planner.
//!
//! The text-to-speech path (`plan_phrases`) times segments by the language's duration rules and
//! makes up the intonation from stress and phrase type. Here the timing and the prosody come from
//! a recording instead (the converter measures them):
//!  - each syllable's vowel starts where the recording's does; its onset consonants come just
//!    before it, its coda just before the next syllable's onset, all at their spoken lengths,
//!    shrunk in proportion when the syllable is faster than that;
//!  - the pitch follows the recording's F0 contour (points every `hop` s, interpolated with the
//!    gestures' cosine ramps) instead of the rule intonation;
//!  - the loudness follows its level contour (the breath's drive), so stressed and emphasised
//!    syllables come out as stressed as they were said;
//!  - a breath group ends where the recording is silent (`end` before the next syllable), and
//!    each group gets the planner's own breath and release.
//!
//! Articulation, aspiration and quantity are the speech planner's (the language's), unchanged.
//! These planners allocate (they run off the audio thread).

use super::inventory::phoneme;
use super::planner::{PlanOptions, diphthong_parts, plan_utterance};
use super::{Intonation, Language, Plan, Segment, Syllable};
use crate::anatomy::human::BodyMix;
use crate::control::score::{ControlKey, Gesture, Targets};
use crate::math::{js_max, js_min};
use serde::{Deserialize, Serialize};

/// A syllable at its time in the recording.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SpokenSyllable {
    pub syl: Syllable,
    /// where its vowel starts (s)
    pub at: f64,
    /// where it stops sounding (s); before the next syllable's onset, there is a pause
    pub end: f64,
}

/// A contour sampled every `hop` seconds from `t0`; a value <= 0 is "nothing here" (unvoiced
/// F0): the contour holds its neighbours across it.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Contour {
    pub t0: f64,
    pub hop: f64,
    pub v: Vec<f64>,
}

impl Contour {
    /// The value at time t: linear between known samples, the nearest known one outside them,
    /// None when the contour has no known sample at all.
    pub fn at(&self, t: f64) -> Option<f64> {
        if self.v.is_empty() || self.hop <= 0.0 {
            return None;
        }
        let x = (t - self.t0) / self.hop;
        let n = self.v.len();
        let i = js_min(js_max(0.0, x.floor()), (n - 1) as f64) as usize;
        let known = |k: usize| self.v[k] > 0.0;
        let mut a = i;
        while a > 0 && !known(a) {
            a -= 1;
        }
        let mut b = (i + 1).min(n - 1);
        while b < n - 1 && !known(b) {
            b += 1;
        }
        match (known(a), known(b)) {
            (true, true) if b > a => {
                let u = js_min(1.0, js_max(0.0, (x - a as f64) / (b - a) as f64));
                Some(self.v[a] + u * (self.v[b] - self.v[a]))
            }
            (true, _) => Some(self.v[a]),
            (_, true) => Some(self.v[b]),
            _ => (0..n).find(|&k| known(k)).map(|k| self.v[k]),
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SpokenOptions {
    pub body: BodyMix,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub language: Option<Language>,
    /// the pitch (Hz)
    pub f0: Contour,
    /// the breath's drive, 0..1 (1: the planner's full breath)
    #[serde(default)]
    pub level: Contour,
    /// a gap longer than this between a syllable's end and the next one's onset is a pause: a new
    /// breath group (s)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pause: Option<f64>,
}

/// spoken consonants keep at least this long when a fast syllable squeezes them (s)
const MIN_CONSONANT: f64 = 0.015;
/// a vowel keeps at least this long (s)
const MIN_VOWEL: f64 = 0.03;
/// the longest a consonant is held over a silence inside a breath group (s)
const HELD_CONSONANT: f64 = 0.35;
/// contour points every this long at most (s)
const STEP: f64 = 0.04;
/// the pitch's gestures win over the planner's and the performer's
const F0_STRENGTH: f64 = 6.0;
/// the level's gestures against the planner's breath (strength 1, drive 1)
const LEVEL_STRENGTH: f64 = 3.0;

fn spoken(segs: &[Segment], body: BodyMix) -> Vec<Segment> {
    segs.iter().map(|c| Segment { ipa: c.ipa.clone(), dur: Some(phoneme(&c.ipa, body).map_or(0.07, |d| d.dur)), ..Default::default() }).collect()
}

fn total(segs: &[Segment]) -> f64 {
    segs.iter().fold(0.0, |s, c| s + c.dur.unwrap_or(0.0))
}

/// Shrink consonants in proportion so they leave `vowel` of `span` (each down to MIN_CONSONANT).
fn fit(groups: [&mut [Segment]; 2], span: f64, vowel: f64) {
    let [a, b] = groups;
    let cons = total(a) + total(b);
    let room = span - vowel;
    if cons <= room || cons <= 0.0 {
        return;
    }
    let scale = js_max(0.0, room) / cons;
    for c in a.iter_mut().chain(b.iter_mut()) {
        c.dur = Some(js_max(MIN_CONSONANT, c.dur.unwrap_or(0.0) * scale));
    }
}

/// Contour points as gestures: one per point, peaking at it, ramping over the step to the
/// neighbours, so neighbouring gestures' weights sum to their strength and the value is
/// interpolated between the points (cosine ramps).
fn contour_gestures(c: &Contour, a: f64, b: f64, key: ControlKey, strength: f64, label: &str, out: &mut Vec<Gesture>) {
    if b <= a {
        return;
    }
    let n = js_max(1.0, ((b - a) / STEP).ceil()) as usize;
    let step = (b - a) / n as f64;
    for k in 0..=n {
        let t = a + step * k as f64;
        let Some(v) = c.at(t) else { return };
        let ramp_in = if k == 0 { 0.02 } else { step };
        let ramp_out = if k == n { 0.02 } else { step };
        out.push(Gesture::new(t, t, ramp_in, ramp_out, strength, Targets::default().with(key, v)).label(label));
    }
}

/// Plan the syllables at their times, one breath group per stretch without a pause.
pub fn plan_spoken(syls: &[SpokenSyllable], o: &SpokenOptions) -> Plan {
    let mut gestures: Vec<Gesture> = Vec::new();
    let mut segments = Vec::new();
    let mut end = 0.0f64;
    let pause = o.pause.unwrap_or(0.12);
    let base_f0 = o.f0.at(syls.first().map_or(0.0, |s| s.at)).unwrap_or(110.0);
    let mut i = 0;
    while i < syls.len() {
        // the breath group: up to a pause after a word (inside a word, a silence is a consonant
        // held: the closure of "kk" in a slow "kaik-ki", not a breath)
        let mut j = i;
        while j < syls.len() - 1 {
            let next_onset = total(&spoken(&syls[j + 1].syl.onset, o.body));
            if syls[j].syl.word_end && syls[j + 1].at - next_onset - syls[j].end > pause {
                break;
            }
            j += 1;
        }
        let mut onsets: Vec<Vec<Segment>> = (i..=j).map(|k| spoken(&syls[k].syl.onset, o.body)).collect();
        let mut codas: Vec<Vec<Segment>> = (i..=j).map(|k| spoken(&syls[k].syl.coda, o.body)).collect();
        // the first onset may not start before the recording does (time 0)
        let first = total(&onsets[0]);
        if first > syls[i].at - 0.01 {
            let scale = js_max(0.0, syls[i].at - 0.01) / first;
            for c in onsets[0].iter_mut() {
                c.dur = Some(js_max(MIN_CONSONANT * 0.5, c.dur.unwrap_or(0.0) * scale));
            }
        }
        for k in i..=j {
            let (span, next) = if k < j { (syls[k + 1].at - syls[k].at, &mut onsets[k + 1 - i][..]) } else { (syls[k].end - syls[k].at, &mut [][..]) };
            // a vowel keeps a third of a short syllable, consonants the rest
            let vowel = js_max(MIN_VOWEL, js_min(0.08, span / 3.0));
            fit([&mut codas[k - i][..], &mut *next], span, vowel);
            // a silence in the recording before the next syllable (within the breath group): the
            // vowel stops where the voice did and the consonants between hold the rest, up to
            // HELD_CONSONANT (a geminate's closure); without consonants the vowel holds it
            if k < j {
                let cons = total(&codas[k - i]) + total(&*next);
                let gap = span - cons - js_max(MIN_VOWEL, syls[k].end - syls[k].at);
                if gap > 0.0 {
                    let held = if let Some(c) = codas[k - i].last_mut() { Some(c) } else { next.first_mut() };
                    if let Some(c) = held {
                        c.dur = Some(c.dur.unwrap_or(0.0) + js_min(gap, HELD_CONSONANT));
                    }
                }
            }
        }
        let mut segs: Vec<Segment> = Vec::new();
        for k in i..=j {
            let s = &syls[k];
            let coda = std::mem::take(&mut codas[k - i]);
            let onset = std::mem::take(&mut onsets[k - i]);
            let vowel_end = if k < j { syls[k + 1].at - total(&onsets[k + 1 - i]) } else { s.end };
            let vdur = js_max(MIN_VOWEL * 0.5, vowel_end - s.at - total(&coda));
            segs.extend(onset);
            let stress = s.syl.nucleus.stress;
            match diphthong_parts(&s.syl.nucleus.ipa) {
                Some((a, b)) => {
                    segs.push(Segment { ipa: a.to_string(), dur: Some(vdur * 0.55), stress, ..Default::default() });
                    segs.push(Segment { ipa: b.to_string(), dur: Some(vdur * 0.45), stress, ..Default::default() });
                }
                None => segs.push(Segment { ipa: s.syl.nucleus.ipa.clone(), dur: Some(vdur), stress, ..Default::default() }),
            }
            let mut coda = coda;
            if let Some(last) = coda.last_mut() {
                last.word_end = Some(s.syl.word_end);
            }
            segs.extend(coda);
        }
        let lead = total(&segs[..syls[i].syl.onset.len()]);
        // the planner lays segments out from t0 + 0.06: start so the first vowel lands on its time
        let t0 = syls[i].at - lead - 0.06;
        let plan = plan_utterance(&segs, &PlanOptions { body: o.body, t0, f0: Some(base_f0), intonation: Some(Intonation::Flat), language: o.language, ..Default::default() });
        // the rule intonation goes: the recording's pitch replaces it
        gestures.extend(plan.gestures.iter().filter(|g| g.label_str() != "pitch").copied());
        let (a, b) = (t0 + 0.04, plan.end);
        contour_gestures(&o.f0, a, b, ControlKey::F0, F0_STRENGTH, "pitch", &mut gestures);
        if !o.level.v.is_empty() {
            contour_gestures(&o.level, a + 0.04, b, ControlKey::BREATH, LEVEL_STRENGTH, "level", &mut gestures);
        }
        segments.extend(plan.segments);
        end = js_max(end, plan.end);
        i = j + 1;
    }
    Plan { gestures, segments, end }
}
