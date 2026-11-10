//! `chimera calibrate …`: ports of `tools/calibrate-vowels.ts` and `tools/calibrate-consonants.ts`.
//! They regenerate the tables the engine embeds (`crates/chimera/src/phonetics/*.generated.json`),
//! written as `JSON.stringify(table, null, 1)` wrote them.

use crate::js::{Json, fixed, pad_end, pad_start};
use crate::repo_path;
use chimera::airway::frequency::{find_peaks, transfer_function};
use chimera::anatomy::contour;
use chimera::anatomy::human::{
    ArticKey, BODY_CHILD, BODY_FEMALE, BODY_MALE, HumanArtic, HumanBody, NEUTRAL, TractModel,
    rest_tip,
};
use chimera::math::{js_max, js_min, js_round, ln, pow};
use chimera::phonetics::inventory::consonants as inventory;
use chimera::phonetics::planner::VowelTable;
use chimera::phonetics::vowel_data::{FI_VOWELS, VOWELS};
use chimera::util::optimize::{NelderMeadOpts, nelder_mead};
use chimera::voice::human_airway::HumanAirway;

const VOWEL_TABLE: &str = "crates/chimera/src/phonetics/vowelTargets.generated.json";
const FI_VOWEL_TABLE: &str = "crates/chimera/src/phonetics/vowelTargets.fi.generated.json";
const CONTOUR_VOWEL_TABLE: &str = "crates/chimera/src/phonetics/vowelTargets.contour.generated.json";
const CONTOUR_FI_VOWEL_TABLE: &str = "crates/chimera/src/phonetics/vowelTargets.fi.contour.generated.json";
const CONSONANT_TABLE: &str = "crates/chimera/src/phonetics/consonantTargets.generated.json";
const CONTOUR_CONSONANT_TABLE: &str = "crates/chimera/src/phonetics/consonantTargets.contour.generated.json";
const BODIES: [(&str, HumanBody); 3] = [
    ("male", BODY_MALE),
    ("female", BODY_FEMALE),
    ("child", BODY_CHILD),
];

/// Split `--out <file>` from the positional arguments.
fn out_option(a: &[String], default: &str) -> Result<(Vec<String>, String), String> {
    let mut rest = Vec::new();
    let mut out = repo_path(default);
    let mut it = a.iter();
    while let Some(x) = it.next() {
        if x == "--out" {
            out = it.next().ok_or("--out needs a file")?.clone();
        } else {
            rest.push(x.clone());
        }
    }
    Ok((rest, out))
}

fn round3(x: f64) -> f64 {
    js_round(x * 1000.0) / 1000.0
}

/// tbX tbY jaw lipAp lipProt lipWidth root larynx curl
const LO: [f64; 9] = [1.2, 5.0, 0.05, 0.12, 0.0, 0.0, -0.9, -1.3, 0.0];
/// the contour anatomy's tongue body reaches further back (the MRI's circle centres go to 0.3 cm)
const LO_CONTOUR: [f64; 9] = [0.2, 5.0, 0.05, 0.12, 0.0, 0.0, -0.9, -1.3, 0.0];
const HI: [f64; 9] = [4.6, 8.8, 2.3, 2.0, 1.4, 1.0, 0.9, 1.3, 1.0];

fn to_artic(p: &[f64]) -> HumanArtic {
    let (tb_x, tb_y, jaw, lip_ap, lip_prot, lip_width, root, larynx, curl) =
        (p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8]);
    let tip = rest_tip(jaw, tb_x, tb_y);
    // rhotic curl raises the tip toward the post-alveolar region
    let tt_x = tip.x - 0.4 * curl;
    let tt_y = tip.y + 2.0 * curl;
    HumanArtic {
        tb_x,
        tb_y,
        jaw,
        lip_ap,
        lip_prot,
        lip_width,
        root,
        larynx,
        tt_x,
        tt_y,
        tt_curl: curl,
        ..NEUTRAL
    }
}

/// Resonance peaks of the airway in posture `a` (frequency-domain model), and its narrowest area.
fn formants(air: &mut HumanAirway, freqs: &[f64], a: &HumanArtic) -> (Vec<f64>, f64) {
    air.apply(a, 0.0);
    let el = air.net.linear_elements();
    let h = transfer_function(&el, air.pharynx.first_node(), freqs, &[air.glottis_port]);
    let pk: Vec<f64> = find_peaks(freqs, &h.mag, 150.0)
        .iter()
        .map(|p| p.freq)
        .collect();
    let mut min_area = f64::INFINITY;
    for &x in air.ph_areas.iter().chain(air.or_areas.iter()) {
        min_area = js_min(min_area, x);
    }
    (pk, min_area)
}

/// Articulatory vowel targets fitted to reference formants with the frequency-domain airway
/// model. `calibrate vowels [male|female|child|all] [--fi] [--contour] [--out file]`; `--fi` fits
/// the Finnish vowel references into the Finnish table and leaves the main table alone;
/// `--contour` calibrates the MRI contour anatomy into its own tables.
pub fn vowels(a: &[String]) -> Result<(), String> {
    let fi = a.iter().any(|x| x == "--fi");
    let contour = a.iter().any(|x| x == "--contour");
    let a: Vec<String> = a.iter().filter(|x| *x != "--fi" && *x != "--contour").cloned().collect();
    let table = match (fi, contour) {
        (false, false) => VOWEL_TABLE,
        (true, false) => FI_VOWEL_TABLE,
        (false, true) => CONTOUR_VOWEL_TABLE,
        (true, true) => CONTOUR_FI_VOWEL_TABLE,
    };
    let (rest, out) = out_option(&a, table)?;
    // the contour model is a fit to the MRI frames' guides and an extrapolation outside them: a
    // soft wall from 5 mm outside the range the MRI covered keeps the fit's tongue body and root
    // near it (the counting has no fully open vowel, so /ɑ/ needs some extrapolation)
    let ranges = if contour { contour::model().guide_range.clone() } else { Vec::new() };
    let refs = if fi { FI_VOWELS } else { VOWELS };
    let which = rest.first().map(String::as_str).unwrap_or("all");
    let n = 700;
    let freqs: Vec<f64> = (0..n)
        .map(|i| 120.0 * pow(4600.0 / 120.0, i as f64 / (n - 1) as f64))
        .collect();
    let mut results = match std::fs::read_to_string(&out) {
        Ok(text) => Json::parse(&text).map_err(|e| format!("{out}: {e}"))?,
        Err(_) => Json::Obj(Vec::new()),
    };
    // Contour anatomy: more starts than the heuristic one, whose fit sometimes ended in a closure
    // (female /i/, child /u/, once male /i/): the table's own posture for the vowel (so a rerun
    // can only improve on it), the adult male's (this run's, or the table's) for the other
    // bodies, and the heuristic start with the tongue body 4 mm lower.
    let mut prev_x: std::collections::HashMap<(String, String), Vec<f64>> = std::collections::HashMap::new();
    if contour && let Ok(text) = std::fs::read_to_string(&out) {
        let v: serde_json::Value = serde_json::from_str(&text).map_err(|e| format!("{out}: {e}"))?;
        for (body, t) in v.as_object().into_iter().flatten() {
            for (ipa, e) in t.as_object().into_iter().flatten() {
                let a = &e["artic"];
                let x: Vec<f64> = ["tbX", "tbY", "jaw", "lipAp", "lipProt", "lipWidth", "root", "larynx", "ttCurl"].iter().map(|k| a[*k].as_f64().unwrap_or(0.0)).collect();
                prev_x.insert((body.clone(), ipa.clone()), x);
            }
        }
    }

    for (bname, body) in BODIES {
        if which != "all" && which != bname {
            continue;
        }
        let body = if contour { body.with_model(TractModel::Contour) } else { body };
        let mut air = HumanAirway::new(96000.0, body);
        let k = body.scale;
        let mut table: Vec<(String, Json)> = Vec::new();
        for vw in refs {
            let t = match bname {
                "male" => vw.male,
                "female" => vw.female,
                _ => vw.child,
            };
            // initial guess from vowel-space position
            let mut x0 = vec![
                3.5 - 1.3 * vw.back + 0.2 * vw.height * (1.0 - vw.back),
                8.0 - 2.0 * vw.height - 0.25 * vw.back,
                0.25 + 1.4 * vw.height,
                if vw.round {
                    0.35 + 0.6 * vw.height
                } else {
                    0.6 + 1.0 * vw.height
                },
                if vw.round { 0.9 } else { 0.1 },
                if vw.round { 0.12 } else { 0.85 },
                0.4 * (1.0 - vw.back) - 0.5 * vw.height * vw.back,
                0.4 * (1.0 - vw.height) * (1.0 - vw.back) - if vw.round { 0.4 } else { 0.0 },
                if vw.ipa == "ɝ" { 0.6 } else { 0.0 },
            ];
            if vw.ipa == "ɯ" {
                x0 = vec![2.6, 7.35, 0.25, 0.5, 0.1, 0.65, 0.4, 0.2, 0.0];
            }
            if contour {
                // the MRI tongues sit ~0.4 cm further back (centre of the fitted circle) than the
                // classic ones; their root guide is relative (0 where the body's position puts it)
                x0[0] -= 0.4;
                x0[6] = 0.0;
            }
            let jaw_prior = 0.2 + 1.5 * vw.height;
            let mut cost = |p: &[f64]| -> f64 {
                let a = to_artic(p);
                let (f, min_area) = formants(&mut air, &freqs, &a);
                if f.len() < 3 {
                    return 50.0;
                }
                let mut c = 0.0;
                let w = [1.0, 1.0, if vw.ipa == "ɝ" { 1.2 } else { 0.45 }];
                for i in 0..3 {
                    c += w[i] * pow(ln(f[i] / t[i]), 2.0);
                }
                // physiology priors (soft)
                let min_ok = 0.22 * k * k;
                if min_area < min_ok {
                    c += 0.4 * pow((min_ok - min_area) / min_ok, 2.0);
                }
                c += 0.004 * pow(p[2] - jaw_prior, 2.0);
                // Finnish: a close vowel keeps a close jaw. With the lips already at full
                // protrusion, the fit lowered /u/'s F2 by opening the jaw behind the lip
                // constriction (jaw 1.8 for [u]), a posture no speaker uses
                if fi && vw.height < 0.2 {
                    c += 0.3 * pow(js_max(0.0, p[2] - (jaw_prior + 0.35)), 2.0);
                }
                let open = vw.height > 0.6;
                if vw.round {
                    let (w_max, p_min, ap_max) = (
                        if open { 0.45 } else { 0.3 },
                        if open { 0.35 } else { 0.6 },
                        0.3 + 0.7 * vw.height,
                    );
                    c += 0.05 * pow(js_max(0.0, p[5] - w_max), 2.0)
                        + 0.05 * pow(js_max(0.0, p_min - p[4]), 2.0)
                        + 0.05 * pow(js_max(0.0, p[3] - ap_max), 2.0);
                } else {
                    let ap_prior = 0.35 + 0.75 * p[2];
                    c += 0.05 * pow(js_max(0.0, 0.55 - p[5]), 2.0)
                        + 0.05 * pow(js_max(0.0, p[4] - 0.35), 2.0)
                        + 0.03 * pow(js_max(0.0, (p[3] - ap_prior).abs() - 0.35), 2.0);
                }
                c += 0.002 * p[6] * p[6] + 0.006 * p[7] * p[7];
                // tbX, tbY, root against the MRI's range (contour anatomy). Not the jaw: its
                // kinematics are the classic model's, and its loadings on the tongue are small
                for (j, pi) in [(1usize, 0usize), (2, 1), (3, 6)] {
                    if let Some([lo, hi]) = ranges.get(j) {
                        let out = js_max(0.0, lo - 0.5 - p[pi]) + js_max(0.0, p[pi] - hi - 0.5);
                        c += 0.1 * out * out;
                    }
                }
                // the tongue body near where the vowel's height and backness put it: many postures
                // give the same formants, and without this the fit wandered (a schwa with the
                // tongue as low as /ɑ/), making every transition through it needlessly long
                c += 0.006 * (pow(p[0] - x0[0], 2.0) + pow(p[1] - x0[1], 2.0));
                if vw.ipa != "ɝ" {
                    c += 0.5 * p[8] * p[8];
                }
                c
            };
            let opts = |step: [f64; 9], max_iter: usize| NelderMeadOpts {
                lo: Some(if contour { LO_CONTOUR } else { LO }.to_vec()),
                hi: Some(HI.to_vec()),
                step: Some(step.to_vec()),
                max_iter: Some(max_iter),
                tol: None,
            };
            let mut best = nelder_mead(
                &mut cost,
                &x0,
                opts([0.4, 0.4, 0.3, 0.25, 0.3, 0.25, 0.3, 0.3, 0.2], 1800),
            );
            if contour {
                let mut starts: Vec<Vec<f64>> = Vec::new();
                if let Some(x) = prev_x.get(&(bname.to_string(), vw.ipa.to_string())) {
                    starts.push(x.clone());
                }
                if bname != "male"
                    && let Some(x) = prev_x.get(&("male".to_string(), vw.ipa.to_string()))
                {
                    starts.push(x.clone());
                }
                let mut low = x0.clone();
                low[1] -= 0.4;
                starts.push(low);
                for st in &starts {
                    let nb = nelder_mead(&mut cost, st, opts([0.3, 0.3, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.1], 1800));
                    if nb.fx < best.fx {
                        best = nb;
                    }
                }
            }
            // restart from the best point to escape shallow minima
            for _ in 0..2 {
                let nb = nelder_mead(
                    &mut cost,
                    &best.x,
                    opts([0.2, 0.2, 0.15, 0.12, 0.15, 0.12, 0.15, 0.15, 0.1], 1000),
                );
                if nb.fx < best.fx {
                    best = nb;
                }
            }
            if contour {
                prev_x.insert((bname.to_string(), vw.ipa.to_string()), best.x.clone());
            }
            let a = to_artic(&best.x);
            let (f, _) = formants(&mut air, &freqs, &a);
            let err: Vec<f64> = (0..3)
                .map(|i| match f.get(i) {
                    Some(&fi) if fi != 0.0 && !fi.is_nan() => (100.0 * (fi - t[i])) / t[i],
                    _ => f64::NAN,
                })
                .collect();
            let nums = |xs: &mut dyn Iterator<Item = f64>| Json::Arr(xs.map(Json::Num).collect());
            let artic = [
                ("tbX", a.tb_x),
                ("tbY", a.tb_y),
                ("jaw", a.jaw),
                ("lipAp", a.lip_ap),
                ("lipProt", a.lip_prot),
                ("lipWidth", a.lip_width),
                ("root", a.root),
                ("larynx", a.larynx),
                ("ttX", a.tt_x),
                ("ttY", a.tt_y),
                ("ttCurl", a.tt_curl),
            ];
            table.push((
                vw.ipa.to_string(),
                Json::Obj(vec![
                    (
                        "artic".into(),
                        Json::Obj(
                            artic
                                .iter()
                                .map(|(k, x)| (k.to_string(), Json::Num(round3(*x))))
                                .collect(),
                        ),
                    ),
                    (
                        "formants".into(),
                        nums(&mut f.iter().take(4).map(|&x| js_round(x))),
                    ),
                    ("target".into(), nums(&mut t.iter().map(|&x| js_round(x)))),
                    (
                        "err".into(),
                        nums(&mut err.iter().map(|&e| js_round(e * 10.0) / 10.0)),
                    ),
                ]),
            ));
            println!(
                "{} {} F={}  T={}  err%={}  tb=({},{}) jaw={} lip={}/{}/{} root={} lx={} curl={}",
                pad_end(bname, 6),
                pad_end(vw.ipa, 2),
                f.iter()
                    .take(3)
                    .map(|x| pad_start(&fixed(*x, 0), 5))
                    .collect::<String>(),
                t.iter()
                    .map(|x| pad_start(&fixed(*x, 0), 5))
                    .collect::<String>(),
                err.iter()
                    .map(|e| pad_start(&fixed(*e, 1), 6))
                    .collect::<String>(),
                fixed(a.tb_x, 2),
                fixed(a.tb_y, 2),
                fixed(a.jaw, 2),
                fixed(a.lip_ap, 2),
                fixed(a.lip_prot, 2),
                fixed(a.lip_width, 2),
                fixed(a.root, 2),
                fixed(a.larynx, 2),
                fixed(a.tt_curl, 2)
            );
        }
        results.set(bname, Json::Obj(table));
    }
    std::fs::write(&out, results.stringify(1)).map_err(|e| format!("{out}: {e}"))?;
    println!("wrote {out}");
    Ok(())
}

/// The main coordinate of each fricative set so the constriction area matches its target
/// (adult-male target × body scale²) in an /a/-like context: bisection on the monotonic contact
/// model. Reads the vowel table (its /ɑ/) from disk. `calibrate consonants [--out file]`
pub fn consonants(a: &[String]) -> Result<(), String> {
    if a.iter().any(|x| x == "--contour") {
        let a: Vec<String> = a.iter().filter(|x| *x != "--contour").cloned().collect();
        return consonants_contour(&a);
    }
    let (_, out) = out_option(a, CONSONANT_TABLE)?;
    let vpath = repo_path(VOWEL_TABLE);
    let vtext = std::fs::read_to_string(&vpath).map_err(|e| format!("{vpath}: {e}"))?;
    let vtable: VowelTable = serde_json::from_str(&vtext).map_err(|e| format!("{vpath}: {e}"))?;
    let mut result: Vec<(String, Json)> = Vec::new();
    for (name, body) in BODIES {
        let mut air = HumanAirway::new(96000.0, body);
        let mut ctx = vtable[name]["ɑ"].artic.apply_to(&NEUTRAL);
        ctx.set(ArticKey::Jaw, 0.55);
        let mut table: Vec<(String, Json)> = Vec::new();
        for p in inventory() {
            let (Some(area), Some(key)) = (p.area, p.cal_key) else {
                continue;
            };
            if area == 0.0 || area.is_nan() {
                continue;
            }
            let target = area * body.scale * body.scale;
            let mut min_area = |v: f64| -> f64 {
                let mut a = p.targets.apply_to(&ctx);
                a.set(key, v);
                air.apply(&a, 0.0);
                let mut m = f64::INFINITY;
                for &x in air.ph_min.iter().chain(air.or_min.iter()) {
                    if x < m {
                        m = x;
                    }
                }
                m
            };
            // search direction: area decreases as the coordinate moves toward closure
            let base = p.targets.get(key).unwrap_or(f64::NAN);
            let (mut lo, mut hi) = (base - 1.2, base + 1.2);
            let decreasing = min_area(hi) < min_area(lo); // area falls as value rises?
            for _ in 0..40 {
                let mid = (lo + hi) / 2.0;
                let area_mid = min_area(mid);
                if (area_mid > target) == decreasing {
                    lo = mid;
                } else {
                    hi = mid;
                }
            }
            let v = (lo + hi) / 2.0;
            let got = min_area(v);
            table.push((
                p.ipa.to_string(),
                Json::Obj(vec![(key.name().to_string(), Json::Num(round3(v)))]),
            ));
            println!(
                "{} {} {}={} area {} (target {})",
                pad_end(name, 6),
                pad_end(p.ipa, 3),
                key.name(),
                fixed(v, 3),
                fixed(got, 3),
                fixed(target, 3)
            );
        }
        result.push((name.to_string(), Json::Obj(table)));
    }
    std::fs::write(&out, Json::Obj(result).stringify(1)).map_err(|e| format!("{out}: {e}"))?;
    Ok(())
}

/// The smallest area of the tract in a posture (cm²).
fn tract_min_area(air: &mut HumanAirway, a: &HumanArtic) -> f64 {
    air.apply(a, 0.0);
    let mut m = f64::INFINITY;
    for &x in air.ph_min.iter().chain(air.or_min.iter()) {
        m = js_min(m, x);
    }
    m
}

/// The smallest area under the oral roof (the fan of rays between the velum and the teeth, cm²):
/// where the tongue body's front meets the palate, apart from the lips and the pharynx.
fn oral_min_area(air: &mut HumanAirway, a: &HumanArtic) -> f64 {
    air.apply(a, 0.0);
    let f = air.frame.as_ref().expect("a frame after apply");
    f.grid.iter().filter(|g| g.region == 2).map(|g| g.area).fold(f64::INFINITY, js_min)
}

/// Where the oral roof's narrowest area is: its distance behind the upper incisors along the
/// centreline (cm).
fn oral_min_behind_teeth(air: &mut HumanAirway, a: &HumanArtic) -> f64 {
    air.apply(a, 0.0);
    let f = air.frame.as_ref().expect("a frame after apply");
    let g = f.grid.iter().filter(|g| g.region == 2).min_by(|x, y| x.area.total_cmp(&y.area)).expect("oral rays");
    f.teeth_s - g.s
}

/// The value of `key` (searched over ±1.2 around `base`) at which the tract's narrowest area is
/// `target`: bisection, the area being monotonic in the coordinate over that span.
fn bisect_area(air: &mut HumanAirway, posture: &HumanArtic, key: ArticKey, base: f64, target: f64) -> (f64, f64) {
    let mut at = |v: f64| {
        let mut a = *posture;
        a.set(key, v);
        tract_min_area(air, &a)
    };
    let (mut lo, mut hi) = (base - 1.2, base + 1.2);
    let decreasing = at(hi) < at(lo);
    for _ in 0..40 {
        let mid = (lo + hi) / 2.0;
        if (at(mid) > target) == decreasing {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    let v = (lo + hi) / 2.0;
    (v, at(v))
}

/// `calibrate consonants --contour [--out file]`: the MRI contour anatomy's consonants. Its palate
/// is lower and its ridge further forward and down than the classic anatomy's, against which the
/// consonants' tip and body targets were tuned by ear, so the same targets sealed what should only
/// narrow (/s/ became a stop, /j/ a [tj], the Finnish /r/'s light contacts full closures). All in
/// each anatomy's own /ɑ/ (jaw 0.55), the classic anatomy's consonant is the reference:
/// - the alveolars' tongue body (`alveolar.body`): as far below the oral roof;
/// - tip closures (stops, nasals, laterals, taps, trills): the contact target as far past the seal;
/// - fricatives and approximants that differ by more than 15 % in their narrowest area: the main
///   coordinate moved until they agree; the tip fricatives also at the same distance behind the
///   teeth (the hiss's front cavity), the palatals from the contour /i/'s body and jaw;
/// - the Finnish /r/'s open and contact tip heights (`r.open`, `r.close`).
fn consonants_contour(a: &[String]) -> Result<(), String> {
    use chimera::anatomy::human::BodyMix;
    use chimera::phonetics::inventory::{ALVEOLAR_BODY, FI_R_CLOSE_Y, FI_R_OPEN_Y, FI_R_X, Manner, phoneme};
    let (_, out) = out_option(a, CONTOUR_CONSONANT_TABLE)?;
    let read = |path: &str| -> Result<VowelTable, String> {
        let p = repo_path(path);
        let text = std::fs::read_to_string(&p).map_err(|e| format!("{p}: {e}"))?;
        serde_json::from_str(&text).map_err(|e| format!("{p}: {e}"))
    };
    let (classic_v, contour_v) = (read(VOWEL_TABLE)?, read(CONTOUR_VOWEL_TABLE)?);
    let mut result: Vec<(String, Json)> = Vec::new();
    for (name, body) in BODIES {
        let mut ca = HumanAirway::new(96000.0, body);
        let mut ma = HumanAirway::new(96000.0, body.with_model(TractModel::Contour));
        let ctx = |t: &VowelTable| {
            let mut c = t[name]["ɑ"].artic.apply_to(&NEUTRAL);
            c.set(ArticKey::Jaw, 0.55);
            c
        };
        let (cc, mc) = (ctx(&classic_v), ctx(&contour_v));
        let classic_body = BodyMix::from(name);
        let mut table: Vec<(String, Json)> = Vec::new();
        // The tongue body alveolars bring forward (the planner's alveolar F2 locus): as far from
        // the oral roof as the classic body is (the narrowest oral ray), with the tip down at rest. At the classic (3.2, 7.4)
        // the MRI tongue's front stood at the ridge and closed the /s/ beside the tip.
        let body_at = |c: &HumanArtic, x: f64, y: f64| {
            let tip = rest_tip(c.jaw, x, y);
            HumanArtic { tb_x: x, tb_y: y, tt_x: tip.x, tt_y: tip.y, ..*c }
        };
        let body_target = oral_min_area(&mut ca, &body_at(&cc, ALVEOLAR_BODY.0, ALVEOLAR_BODY.1));
        let mut lo = ALVEOLAR_BODY.1 - 1.5;
        let mut hi = ALVEOLAR_BODY.1;
        for _ in 0..40 {
            let mid = 0.5 * (lo + hi);
            if oral_min_area(&mut ma, &body_at(&mc, ALVEOLAR_BODY.0, mid)) > body_target {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        let alv = (ALVEOLAR_BODY.0, 0.5 * (lo + hi));
        table.push(("alveolar.body".to_string(), Json::Obj(vec![("tbX".to_string(), Json::Num(round3(alv.0))), ("tbY".to_string(), Json::Num(round3(alv.1)))])));
        println!("{} alveolar body tbY {} -> {} (area {}, classic {})", pad_end(name, 6), fixed(ALVEOLAR_BODY.1, 3), fixed(alv.1, 3), fixed(oral_min_area(&mut ma, &body_at(&mc, alv.0, alv.1)), 3), fixed(body_target, 3));
        for p in inventory() {
            // Tip closures (/t d n l ɾ/, the affricates' stops): the classic targets reach 0.3–0.4 cm
            // past where the tip seals on the classic ridge; on the MRI's lower ridge the same
            // targets pressed 1.2 cm past it, and the tip, climbing out of that overshoot, let go
            // late ("nenä": the /n/ 8 ms longer, eating the /æ/). The target moves with the seal.
            if matches!(p.manner, Manner::Stop | Manner::Nasal | Manner::Affricate | Manner::Tap | Manner::Trill | Manner::Lateral) && p.dominant.contains(&ArticKey::TtY) {
                let Some(def) = phoneme(p.ipa, classic_body) else { continue };
                let Some(y) = def.targets.get(ArticKey::TtY) else { continue };
                let alveolar = p.place == "alveolar" && matches!(p.manner, Manner::Stop | Manner::Nasal | Manner::Affricate | Manner::Tap);
                let with_body = |c: &HumanArtic, b: (f64, f64)| if alveolar { HumanArtic { tb_x: b.0, tb_y: b.1, ..*c } } else { *c };
                // (a lateral's midline seal, measured without its side channel)
                let midline = |a: HumanArtic| HumanArtic { lateral: 0.0, ..a };
                let (pc, pm) = (midline(with_body(&def.targets.apply_to(&cc), ALVEOLAR_BODY)), midline(with_body(&def.targets.apply_to(&mc), alv)));
                let (seal_c, got_c) = bisect_area(&mut ca, &pc, ArticKey::TtY, y - 0.4, 0.002);
                let (seal_m, got_m) = bisect_area(&mut ma, &pm, ArticKey::TtY, y - 0.4, 0.002);
                if (got_c - 0.002).abs() > 0.001 || (got_m - 0.002).abs() > 0.001 {
                    println!("{} {} no seal to keep the overshoot of (areas {}, {})", pad_end(name, 6), pad_end(p.ipa, 3), fixed(got_c, 3), fixed(got_m, 3));
                    continue;
                }
                let ym = y + (seal_m - seal_c);
                if (ym - y).abs() > 0.02 {
                    table.push((p.ipa.to_string(), Json::Obj(vec![("ttY".to_string(), Json::Num(round3(ym)))])));
                    println!("{} {} contact ttY {} -> {} (seals at {}, classic {})", pad_end(name, 6), pad_end(p.ipa, 3), fixed(y, 3), fixed(ym, 3), fixed(seal_m, 3), fixed(seal_c, 3));
                }
                continue;
            }
            // (not the laterals: their side channel keeps them open in either anatomy, 0.28 cm² in
            // both in running speech)
            if !matches!(p.manner, Manner::Fricative | Manner::Approximant) {
                continue;
            }
            let key = match p.cal_key {
                Some(k) => k,
                None if p.dominant.contains(&ArticKey::TtY) => ArticKey::TtY,
                None if p.dominant.contains(&ArticKey::TbY) => ArticKey::TbY,
                None => continue,
            };
            // the classic anatomy's consonant, calibrated values included; an alveolar fricative
            // with the tongue body each anatomy brings forward for it
            let Some(def) = phoneme(p.ipa, classic_body) else { continue };
            let alveolar = p.place == "alveolar" && p.manner == Manner::Fricative;
            let with_body = |c: &HumanArtic, b: (f64, f64)| if alveolar { HumanArtic { tb_x: b.0, tb_y: b.1, ..*c } } else { *c };
            let target = tract_min_area(&mut ca, &with_body(&def.targets.apply_to(&cc), ALVEOLAR_BODY));
            if target < 0.005 {
                continue;
            }
            let posture = with_body(&def.targets.apply_to(&mc), alv);
            let now = tract_min_area(&mut ma, &posture);
            if (now - target).abs() <= 0.15 * target {
                continue;
            }
            let base = def.targets.get(key).unwrap_or_else(|| posture.get(key));
            // The palatals (/j ç ʝ/) narrow under the hard palate. The MRI's palate is lower and
            // its ridge further back than the classic one's; with the classic targets' jaw and
            // a free tip, the blade met the ridge first and the /j/ became a coronal [tj]
            // whatever the body's height. They take the contour /i/'s body front–back and jaw
            // (the MRI vowel the /j/ is a tighter version of) and rise until the opening matches.
            if p.place == "palatal" && key == ArticKey::TbY {
                let i = contour_v[name]["i"].artic;
                let (ix, ij) = (i.get(ArticKey::TbX).unwrap_or(posture.tb_x), i.get(ArticKey::Jaw).unwrap_or(posture.jaw));
                let at = |y: f64| {
                    let tip = rest_tip(ij, ix, y);
                    HumanArtic { tb_x: ix, tb_y: y, jaw: ij, tt_x: tip.x, tt_y: tip.y, ..posture }
                };
                let classic_tip = {
                    let c = def.targets.apply_to(&cc);
                    let tip = rest_tip(c.jaw, c.tb_x, c.tb_y);
                    HumanArtic { tt_x: tip.x, tt_y: tip.y, ..c }
                };
                let target = oral_min_area(&mut ca, &classic_tip);
                let (mut lo, mut hi) = (i.get(ArticKey::TbY).unwrap_or(posture.tb_y) - 0.5, base + 0.5);
                for _ in 0..40 {
                    let mid = 0.5 * (lo + hi);
                    if oral_min_area(&mut ma, &at(mid)) > target {
                        lo = mid;
                    } else {
                        hi = mid;
                    }
                }
                let y = 0.5 * (lo + hi);
                let got = oral_min_area(&mut ma, &at(y));
                let (wc, wm) = (oral_min_behind_teeth(&mut ca, &classic_tip), oral_min_behind_teeth(&mut ma, &at(y)));
                table.push((p.ipa.to_string(), Json::Obj(vec![("tbX".to_string(), Json::Num(round3(ix))), ("tbY".to_string(), Json::Num(round3(y))), ("jaw".to_string(), Json::Num(round3(ij)))])));
                println!("{} {} tbY: {} -> {} (tbX {}, jaw {}) area {} -> {} (classic {}), narrowest {} cm behind the teeth (classic {})", pad_end(name, 6), pad_end(p.ipa, 3), fixed(base, 3), fixed(y, 3), fixed(ix, 2), fixed(ij, 2), fixed(now, 3), fixed(got, 3), fixed(target, 3), fixed(wm, 2), fixed(wc, 2));
                continue;
            }
            // A body raised toward the palate (/j ç ʝ/) with the body as far forward as the
            // classic targets put it (tbX 3.8, beyond the MRI's 3.57) pressed the dorsum's front
            // onto the ridge at any height: such a body steps back, 2 mm at a time, until the
            // height alone can give the opening.
            // A tip fricative's hiss is shaped by the cavity in front of its constriction (the
            // sibilant's spectral peak). The MRI ridge sits lower and further forward against the
            // incisors than the classic one: with the classic tip position the /s/ narrowed 1 cm
            // behind the teeth instead of 2, its peak 1 kHz higher and its 2–4 kHz 12 dB weaker (a
            // thin, whistly [s]). The tip moves back (and up to the same opening) until the
            // constriction is as far behind the teeth as the classic one.
            if key == ArticKey::TtY && p.manner == Manner::Fricative && p.dominant.contains(&ArticKey::TtX) {
                let x0 = def.targets.get(ArticKey::TtX).unwrap_or(posture.tt_x);
                let where_c = oral_min_behind_teeth(&mut ca, &with_body(&def.targets.apply_to(&cc), ALVEOLAR_BODY));
                let mut best: Option<(f64, f64, f64, f64)> = None; // (|Δ where|, ttX, ttY, area)
                for i in 0..=24 {
                    let x = x0 + 0.2 - 0.05 * i as f64;
                    let at_x = HumanArtic { tt_x: x, ..posture };
                    let (y, got) = bisect_area(&mut ma, &at_x, key, base, target);
                    if (got - target).abs() > 0.1 * target {
                        continue;
                    }
                    let miss = (oral_min_behind_teeth(&mut ma, &HumanArtic { tt_y: y, ..at_x }) - where_c).abs();
                    if best.is_none_or(|b| miss < b.0 - 1e-9) {
                        best = Some((miss, x, y, got));
                    }
                }
                if let Some((miss, x, y, got)) = best {
                    table.push((p.ipa.to_string(), Json::Obj(vec![("ttX".to_string(), Json::Num(round3(x))), ("ttY".to_string(), Json::Num(round3(y)))])));
                    println!("{} {} ttX {} -> {}, ttY {} -> {}: area {} -> {} (classic {}), narrowest {} cm behind the teeth (classic {})", pad_end(name, 6), pad_end(p.ipa, 3), fixed(x0, 2), fixed(x, 2), fixed(base, 3), fixed(y, 3), fixed(now, 3), fixed(got, 3), fixed(target, 3), fixed(where_c + miss.copysign(1.0), 2), fixed(where_c, 2));
                    continue;
                }
            }
            let mut posture = posture;
            let mut entry = Vec::new();
            let mut found = None;
            for step in 0..8 {
                if key == ArticKey::TbY && step > 0 {
                    let x = js_min(def.targets.get(ArticKey::TbX).unwrap_or(posture.tb_x), contour::model().guide_range[1][1]) - 0.2 * (step - 1) as f64;
                    posture.tb_x = x;
                }
                let (v, got) = bisect_area(&mut ma, &posture, key, base, target);
                if (got - target).abs() <= 0.1 * target {
                    found = Some((v, got));
                    break;
                }
                if key != ArticKey::TbY {
                    found = Some((v, got));
                    break;
                }
            }
            let Some((v, got)) = found else {
                println!("{} {} {}: no posture gives the classic opening {}", pad_end(name, 6), pad_end(p.ipa, 3), key.name(), fixed(target, 3));
                continue;
            };
            if key == ArticKey::TbY && Some(posture.tb_x) != def.targets.get(ArticKey::TbX) {
                entry.push(("tbX".to_string(), Json::Num(round3(posture.tb_x))));
            }
            entry.push((key.name().to_string(), Json::Num(round3(v))));
            table.push((p.ipa.to_string(), Json::Obj(entry)));
            println!("{} {} {}: {} -> {} (tbX {}) area {} -> {} (classic {})", pad_end(name, 6), pad_end(p.ipa, 3), key.name(), fixed(base, 3), fixed(v, 3), fixed(posture.tb_x, 2), fixed(now, 3), fixed(got, 3), fixed(target, 3));
        }
        // The Finnish /r/: the open phase as open as the classic one, and the contact target as
        // far past the seal as the classic one (it is a static seal in both; the tip only touches
        // in the 12 ms it is held, which the overshoot past the seal decides)
        let tip = |c: &HumanArtic, y: f64| HumanArtic { tt_x: FI_R_X, tt_y: y, ..*c };
        let target = tract_min_area(&mut ca, &tip(&cc, FI_R_OPEN_Y));
        let (open, got) = bisect_area(&mut ma, &tip(&mc, FI_R_OPEN_Y), ArticKey::TtY, FI_R_OPEN_Y, target);
        let (seal_c, _) = bisect_area(&mut ca, &tip(&cc, FI_R_CLOSE_Y), ArticKey::TtY, FI_R_CLOSE_Y, 0.002);
        let (seal_m, _) = bisect_area(&mut ma, &tip(&mc, FI_R_CLOSE_Y), ArticKey::TtY, FI_R_CLOSE_Y, 0.002);
        let close = seal_m + (FI_R_CLOSE_Y - seal_c);
        table.push(("r.open".to_string(), Json::Obj(vec![("ttY".to_string(), Json::Num(round3(open)))])));
        table.push(("r.close".to_string(), Json::Obj(vec![("ttY".to_string(), Json::Num(round3(close)))])));
        println!("{} r       open ttY {} -> {} (area {}, classic {}); contact {} -> {} (seals at {}, classic {})", pad_end(name, 6), fixed(FI_R_OPEN_Y, 3), fixed(open, 3), fixed(got, 3), fixed(target, 3), fixed(FI_R_CLOSE_Y, 3), fixed(close, 3), fixed(seal_m, 3), fixed(seal_c, 3));
        result.push((name.to_string(), Json::Obj(table)));
    }
    std::fs::write(&out, Json::Obj(result).stringify(1)).map_err(|e| format!("{out}: {e}"))?;
    println!("wrote {out}");
    Ok(())
}
