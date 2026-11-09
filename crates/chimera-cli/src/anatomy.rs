//! `chimera anatomy fit <contours.json> [--out file] [--frames file]`: fits the statistical
//! contour model (`crates/chimera/src/anatomy/contour.rs`) to MRI contours registered by
//! `tools/contour-model/extract.py`, and writes `contourModel.generated.json`.
//!
//! 1. Each frame's tongue outline is measured on the model's lines (where each line leaves the
//!    tongue). Points below the MRI field's lower edge (plus 3 mm) don't count.
//! 2. The jaw opening is measured on the frame (how far the lower incisors are below the
//!    speaker's most closed frame), and the classic tongue is fitted to the frame's measurements
//!    (tongue-body centre and root): these are the frame's guides, in the engine's own units.
//! 3. Per line, the measured distance is regressed on the guides with a separate intercept per
//!    speaker (pooled within-speaker regression): the loadings are the common articulation, the
//!    intercepts' mean is the mean speaker. The residuals' principal components are kept as the
//!    model's shape modes (not driven yet).
//! 4. The walls are the speakers' mean posterior pharyngeal wall and hard palate, joined to the
//!    classic wall below the MRI field and to the classic incisor; the soft palate's length,
//!    thickness and closed/open directions are the frames' medians.

use crate::js::fixed;
use crate::repo_path;
use chimera::anatomy::contour::{self, ContourModel, GUIDES, N_GUIDES, N_LINES, N_PHAR, VelumShape};
use chimera::anatomy::geom::{Polyline, Vec2, dist, v};
use chimera::anatomy::human::{ArticPatch, BODY_MALE, BodyMix, HumanArtic, HumanVocalTract, NEUTRAL, rest_tip};
use chimera::phonetics::planner::vowel_artic;
use chimera::math::{PI, atan2};
use chimera::util::optimize::{NelderMeadOpts, nelder_mead};
use serde_json::{Value, json};

const MODEL_PATH: &str = "crates/chimera/src/anatomy/contourModel.generated.json";
/// how far above the MRI field's lower edge a measurement must lie (cm)
const CUT_MARGIN: f64 = 0.3;
/// the jaw opening of each speaker's most closed frame (cm at the incisors); counting has /s/ in
/// "six" and "seven", nearly closed
const JAW_CLOSED: f64 = 0.15;
/// the classic model's posterior pharyngeal wall and palate (adult male body cm; `human.rs`)
const CLASSIC_WALL: [[f64; 2]; 9] = [[-1.0, -1.5], [-1.1, 1.5], [-1.2, 3.6], [-1.3, 5.6], [-1.38, 7.5], [-1.33, 8.9], [-1.05, 10.1], [-0.45, 10.9], [0.4, 11.3]];
const PALATE_START: [f64; 2] = [0.93, 9.6];
const INCISOR: [[f64; 2]; 2] = [[6.073, 8.3], [6.193, 7.95]];
/// the velum's hinge, p(1.0, 9.75)
const HINGE: Vec2 = v(0.93, 9.75);
/// the oral lines (from the first oral line) the tongue body's circle is fitted to: 160° to 60°
const DORSUM: std::ops::Range<usize> = 2..13;
/// the line the root guide is measured on (y 5.5 cm)
const ROOT_LINE: usize = 3;

fn point_on(i: usize, s: f64) -> Vec2 {
    let (o, d) = contour::line(i);
    v(o.x + d.x * s, o.y + d.y * s)
}

struct Frame {
    speaker: usize,
    s: [f64; N_LINES],
    guides: [f64; N_GUIDES],
    classic_rms: f64,
}

fn pts(val: &Value) -> Vec<Vec2> {
    val.as_array().map(|a| a.iter().map(|p| v(p[0].as_f64().unwrap_or(f64::NAN), p[1].as_f64().unwrap_or(f64::NAN))).collect()).unwrap_or_default()
}

fn closed(points: &[Vec2]) -> Polyline {
    let mut pl = Polyline::with_capacity(points.len() + 1);
    for p in points {
        pl.push(*p);
    }
    if let Some(p) = points.first() {
        pl.push(*p);
    }
    pl
}

fn median(xs: &mut [f64]) -> f64 {
    xs.sort_by(|a, b| a.total_cmp(b));
    let n = xs.len();
    if n == 0 {
        return f64::NAN;
    }
    if n % 2 == 1 { xs[n / 2] } else { 0.5 * (xs[n / 2 - 1] + xs[n / 2]) }
}

fn quantile(xs: &mut [f64], q: f64) -> f64 {
    xs.sort_by(|a, b| a.total_cmp(b));
    if xs.is_empty() {
        return f64::NAN;
    }
    let i = (q * (xs.len() - 1) as f64).round() as usize;
    xs[i]
}

/// x of a polyline at height y (linear between its points; the polyline runs bottom to top), or NaN.
fn x_at(line: &[Vec2], y: f64) -> f64 {
    for w in line.windows(2) {
        let (a, b) = (w[0], w[1]);
        if (a.y <= y && y <= b.y) || (b.y <= y && y <= a.y) {
            let t = if (b.y - a.y).abs() < 1e-12 { 0.5 } else { (y - a.y) / (b.y - a.y) };
            return a.x + t * (b.x - a.x);
        }
    }
    f64::NAN
}

/// y of a polyline at x (the first stretch spanning x), or NaN.
fn y_at(line: &[Vec2], x: f64) -> f64 {
    for w in line.windows(2) {
        let (a, b) = (w[0], w[1]);
        if (a.x <= x && x <= b.x) || (b.x <= x && x <= a.x) {
            let t = if (b.x - a.x).abs() < 1e-12 { 0.5 } else { (x - a.x) / (b.x - a.x) };
            return a.y + t * (b.y - a.y);
        }
    }
    f64::NAN
}

/// The classic tongue's measurements for a posture (male body).
fn classic_s(tract: &mut HumanVocalTract, a: &HumanArtic, buf: &mut [f64]) -> [f64; N_LINES] {
    let f = tract.compute_new(a);
    let mut s = [0.0; N_LINES];
    contour::measure(&closed(&f.tongue), &mut s, buf);
    s
}

fn artic(g: &[f64]) -> HumanArtic {
    let (jaw, tb_x, tb_y, root) = (g[0], g[1], g[2], g[3]);
    let tip = rest_tip(jaw, tb_x, tb_y);
    HumanArtic { jaw, tb_x, tb_y, root, tt_x: tip.x, tt_y: tip.y, ..NEUTRAL }
}

/// Solve the symmetric positive system A·x = b (Gaussian elimination with partial pivoting).
fn solve(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Vec<f64> {
    let n = b.len();
    for c in 0..n {
        let p = (c..n).max_by(|&i, &j| a[i][c].abs().total_cmp(&a[j][c].abs())).unwrap();
        a.swap(c, p);
        b.swap(c, p);
        let d = a[c][c];
        for r in c + 1..n {
            let f = a[r][c] / d;
            if f == 0.0 {
                continue;
            }
            for k in c..n {
                a[r][k] -= f * a[c][k];
            }
            b[r] -= f * b[c];
        }
    }
    let mut x = vec![0.0; n];
    for r in (0..n).rev() {
        let mut s = b[r];
        for k in r + 1..n {
            s -= a[r][k] * x[k];
        }
        x[r] = s / a[r][r];
    }
    x
}

/// The leading eigenvectors of a symmetric matrix (power iteration with deflation).
fn eigen(mut m: Vec<Vec<f64>>, k: usize) -> Vec<(f64, Vec<f64>)> {
    let n = m.len();
    let mut out = Vec::new();
    for e in 0..k {
        let mut x: Vec<f64> = (0..n).map(|i| 1.0 + 0.1 * ((i + e) % 7) as f64).collect();
        let mut lam = 0.0;
        for _ in 0..500 {
            let y: Vec<f64> = (0..n).map(|i| (0..n).map(|j| m[i][j] * x[j]).sum()).collect();
            let norm = y.iter().map(|a| a * a).sum::<f64>().sqrt();
            if norm < 1e-15 {
                break;
            }
            lam = norm;
            x = y.iter().map(|a| a / norm).collect();
        }
        for i in 0..n {
            for j in 0..n {
                m[i][j] -= lam * x[i] * x[j];
            }
        }
        out.push((lam, x));
    }
    out
}

pub fn run(a: &[String]) -> Result<(), String> {
    match a.first().map(String::as_str) {
        Some("fit") => fit(&a[1..]),
        Some("frame") => frame(&a[1..]),
        _ => Err("usage: chimera anatomy fit <contours.json> [--out file] [--frames file]\n       chimera anatomy frame [body[/contour]] [vowel | artic.json]".into()),
    }
}

/// `chimera anatomy frame [body[/contour]] [vowel | artic.json]`: the tract geometry (outlines,
/// grid, areas) of a posture as JSON on stdout: a vowel's calibrated target, an articulation
/// patch from a file, or the neutral posture.
fn frame(a: &[String]) -> Result<(), String> {
    let body = BodyMix::from(a.first().map(String::as_str).unwrap_or("male"));
    let what = a.get(1).map(String::as_str).unwrap_or("");
    let patch: ArticPatch = if what.ends_with(".json") {
        serde_json::from_str(&std::fs::read_to_string(what).map_err(|e| format!("{what}: {e}"))?).map_err(|e| format!("{what}: {e}"))?
    } else if what.is_empty() {
        ArticPatch::default()
    } else {
        vowel_artic(what, body).ok_or(format!("no calibrated vowel {what:?}"))?
    };
    let artic = patch.apply_to(&NEUTRAL);
    let mut tract = HumanVocalTract::new(body.body());
    let f = tract.compute_new(&artic);
    println!("{}", serde_json::to_string(&json!({ "body": body, "artic": artic, "frame": f })).map_err(|e| e.to_string())?);
    Ok(())
}

fn fit(a: &[String]) -> Result<(), String> {
    let mut input = None;
    let mut out = repo_path(MODEL_PATH);
    let mut frames_out = None;
    let mut it = a.iter();
    while let Some(x) = it.next() {
        match x.as_str() {
            "--out" => out = it.next().ok_or("--out needs a file")?.clone(),
            "--frames" => frames_out = Some(it.next().ok_or("--frames needs a file")?.clone()),
            _ => input = Some(x.clone()),
        }
    }
    let input = input.ok_or("chimera anatomy fit <contours.json>")?;
    let doc: Value = serde_json::from_str(&std::fs::read_to_string(&input).map_err(|e| format!("{input}: {e}"))?).map_err(|e| format!("{input}: {e}"))?;
    let speakers = doc["speakers"].as_array().ok_or("no speakers")?;
    let mut tract = HumanVocalTract::new(BODY_MALE);
    let mut buf = vec![0.0; 64];
    let mut frames: Vec<Frame> = Vec::new();
    let mut walls: Vec<Vec<Vec2>> = Vec::new();
    let mut roofs: Vec<Vec<Vec2>> = Vec::new();
    let (mut vel_len, mut vel_half, mut ang_closed, mut ang_open) = (Vec::new(), Vec::new(), Vec::new(), Vec::new());
    for (si, sp) in speakers.iter().enumerate() {
        let cut = pts(&sp["cut"]);
        let (c0, c1) = (cut[0], cut[1]);
        let above_cut = |q: Vec2| q.y > c0.y + (q.x - c0.x) * (c1.y - c0.y) / (c1.x - c0.x) + CUT_MARGIN;
        let mut wall = pts(&sp["pharWall"]);
        wall.sort_by(|p, q| p.y.total_cmp(&q.y));
        walls.push(wall);
        let mut roof = pts(&sp["roof"]);
        roof.sort_by(|p, q| p.x.total_cmp(&q.x));
        roofs.push(roof);
        let fs = sp["frames"].as_array().ok_or("no frames")?;
        // jaw: the lower incisors' drop from the speaker's most closed frame (97th percentile height)
        let teeth: Vec<Option<Vec2>> = fs.iter().map(|f| pts(&json!([f["teethTop"]])).first().copied().filter(|p| p.x.is_finite())).collect();
        let mut ys: Vec<f64> = teeth.iter().flatten().map(|p| p.y).collect();
        let top_y = quantile(&mut ys, 0.97);
        let top = teeth.iter().flatten().min_by(|p, q| (p.y - top_y).abs().total_cmp(&(q.y - top_y).abs())).copied().ok_or("no teeth")?;
        for (fi, f) in fs.iter().enumerate() {
            // soft palate
            let vel = pts(&f["velum"]);
            if vel.len() > 8 {
                let tip = vel.iter().copied().max_by(|p, q| dist(*p, HINGE).total_cmp(&dist(*q, HINGE))).unwrap();
                let len = dist(tip, HINGE);
                // area of the outline (shoelace) over its length: the mean thickness
                let mut area = 0.0;
                for i in 0..vel.len() {
                    let (p, q) = (vel[i], vel[(i + 1) % vel.len()]);
                    area += p.x * q.y - q.x * p.y;
                }
                let ang = atan2(tip.y - HINGE.y, tip.x - HINGE.x) * 180.0 / PI;
                let ang = if ang < 0.0 { ang + 360.0 } else { ang };
                vel_len.push(len);
                vel_half.push(0.5 * (0.5 * area.abs()) / len);
                match f["closed"].as_i64() {
                    Some(1) => ang_closed.push(ang),
                    Some(0) => ang_open.push(ang),
                    _ => {}
                }
            }
            let tongue = pts(&f["tongue"]);
            if tongue.len() < 10 {
                continue;
            }
            let mut s = [0.0; N_LINES];
            contour::measure(&closed(&tongue), &mut s, &mut buf);
            for (i, x) in s.iter_mut().enumerate() {
                let (o, d) = contour::line(i);
                let q = v(o.x + d.x * *x, o.y + d.y * *x);
                if !x.is_finite() || !above_cut(q) {
                    *x = f64::NAN;
                }
            }
            let jaw = match teeth[fi] {
                Some(p) => JAW_CLOSED + (top.y - p.y).max(0.0) * 1.05,
                None => NEUTRAL.jaw,
            };
            // the classic tongue that fits this frame best: its body centre and root
            let mut cost = |x: &[f64]| -> f64 {
                let sc = classic_s(&mut tract, &artic(&[jaw, x[0], x[1], x[2]]), &mut buf);
                let mut c = 0.0;
                for i in 0..N_LINES {
                    if s[i].is_finite() {
                        let d = if sc[i].is_finite() { sc[i] - s[i] } else { 2.0 };
                        c += d * d;
                    }
                }
                c + 0.01 * x[2] * x[2]
            };
            let opts = |step: f64| NelderMeadOpts { step: Some(vec![step, step, step]), lo: Some(vec![1.0, 4.5, -1.5]), hi: Some(vec![5.0, 9.0, 1.5]), max_iter: Some(600), tol: Some(1e-9) };
            let mut best = nelder_mead(&mut cost, &[NEUTRAL.tb_x, NEUTRAL.tb_y, 0.0], opts(0.4));
            let again = nelder_mead(&mut cost, &best.x, opts(0.15));
            if again.fx < best.fx {
                best = again;
            }
            let n_valid = s.iter().filter(|x| x.is_finite()).count().max(1);
            // the guides, measured on the frame: the tongue body's centre is the centre of the
            // classic tongue's circle (radius 2.25 cm) fitted to the dorsum, the root its position
            // on the 5.5 cm line (made relative below)
            let dorsum: Vec<Vec2> = (N_PHAR + DORSUM.start..N_PHAR + DORSUM.end).filter(|&i| s[i].is_finite()).map(|i| point_on(i, s[i])).collect();
            let circle = |x: &[f64]| -> f64 { dorsum.iter().map(|p| (dist(*p, v(x[0], x[1])) - BODY_MALE.tongue_radius).powi(2)).sum() };
            let c = nelder_mead(circle, &[2.5, 6.8], NelderMeadOpts { step: Some(vec![0.3, 0.3]), max_iter: Some(800), tol: Some(1e-12), ..Default::default() });
            let tb_x = 0.5 + (c.x[0] - 0.5) / 0.86;
            let root_x = point_on(ROOT_LINE, s[ROOT_LINE]).x;
            frames.push(Frame { speaker: si, s, guides: [jaw, tb_x, c.x[1], root_x], classic_rms: (best.fx / n_valid as f64).sqrt() });
        }
        eprintln!("speaker {}: {} frames", sp["id"], fs.len());
    }
    let n_sp = speakers.len();
    // The root guide: where the root stands on its line beyond what the tongue body's position
    // predicts (pooled within speakers, so a speaker's deeper pharynx isn't a root position), so
    // 0 is the root's usual place for the body's position, + forward (cm).
    {
        let mut sums = vec![(0.0, [0.0; 3], 0usize); n_sp];
        for f in &frames {
            let e = &mut sums[f.speaker];
            e.0 += f.guides[3];
            e.1[0] += f.guides[1];
            e.1[1] += f.guides[2];
            e.2 += 1;
        }
        let centred = |f: &Frame| -> [f64; 3] {
            let e = &sums[f.speaker];
            let n = e.2 as f64;
            [f.guides[3] - e.0 / n, f.guides[1] - e.1[0] / n, f.guides[2] - e.1[1] / n]
        };
        let (mut ata, mut atb) = (vec![vec![0.0; 2]; 2], vec![0.0; 2]);
        for f in &frames {
            let [r, x, y] = centred(f);
            ata[0][0] += x * x;
            ata[0][1] += x * y;
            ata[1][0] += x * y;
            ata[1][1] += y * y;
            atb[0] += x * r;
            atb[1] += y * r;
        }
        let b = solve(ata, atb);
        for f in frames.iter_mut() {
            let [r, x, y] = centred(f);
            f.guides[3] = r - b[0] * x - b[1] * y;
        }
    }

    // ---- pooled within-speaker regression per line
    let g0 = contour::neutral_guides();
    let mut mean = vec![0.0; N_LINES];
    let mut loadings = vec![[0.0; N_GUIDES]; N_LINES];
    let mut line_rms = vec![0.0; N_LINES];
    let mut line_sd = vec![0.0; N_LINES];
    let mut line_n = vec![0usize; N_LINES];
    let mut resid = vec![vec![f64::NAN; N_LINES]; frames.len()];
    // each speaker's intercept per line (None where the speaker has too few frames on the line)
    let mut icpt = vec![vec![None; n_sp]; N_LINES];
    for i in 0..N_LINES {
        let rows: Vec<&Frame> = frames.iter().filter(|f| f.s[i].is_finite()).collect();
        let present: Vec<usize> = (0..n_sp).filter(|&s| rows.iter().filter(|f| f.speaker == s).count() >= 5).collect();
        let rows: Vec<&Frame> = rows.into_iter().filter(|f| present.contains(&f.speaker)).collect();
        let p = present.len() + N_GUIDES;
        let mut ata = vec![vec![0.0; p]; p];
        let mut atb = vec![0.0; p];
        let feat = |f: &Frame| -> Vec<f64> {
            let mut x = vec![0.0; p];
            x[present.iter().position(|&s| s == f.speaker).unwrap()] = 1.0;
            for j in 0..N_GUIDES {
                x[present.len() + j] = f.guides[j] - g0[j];
            }
            x
        };
        for f in &rows {
            let x = feat(f);
            for r in 0..p {
                for c in 0..p {
                    ata[r][c] += x[r] * x[c];
                }
                atb[r] += x[r] * f.s[i];
            }
        }
        // a light ridge on the loadings (not on the intercepts)
        for j in 0..N_GUIDES {
            ata[present.len() + j][present.len() + j] += 0.5;
        }
        let beta = solve(ata, atb);
        for (k, &sp) in present.iter().enumerate() {
            icpt[i][sp] = Some(beta[k]);
        }
        for j in 0..N_GUIDES {
            loadings[i][j] = beta[present.len() + j];
        }
        let m_all = rows.iter().map(|f| f.s[i]).sum::<f64>() / rows.len() as f64;
        let (mut se, mut sv) = (0.0, 0.0);
        for (fi, f) in frames.iter().enumerate() {
            if !f.s[i].is_finite() || !present.contains(&f.speaker) {
                continue;
            }
            let x = feat(f);
            let pred: f64 = x.iter().zip(&beta).map(|(a, b)| a * b).sum();
            let r = f.s[i] - pred;
            resid[fi][i] = r;
            se += r * r;
            sv += (f.s[i] - m_all) * (f.s[i] - m_all);
        }
        line_n[i] = rows.len();
        line_rms[i] = (se / rows.len() as f64).sqrt();
        line_sd[i] = (sv / rows.len() as f64).sqrt();
    }

    // The mean speaker. The lowest lines lie below the MRI field of some speakers, and a mean over
    // the rest would step wherever a speaker drops out: chain instead, from a line all speakers
    // reach, adding the mean change from line to line over the speakers on both.
    chain(&icpt, &mut mean);
    // Light smoothing along the surface (the MRI's 1.2 mm pixels and the speakers' differences
    // left ripples of ~1 mm that the real surface doesn't have). It works on the points and their
    // displacements in the plane, so it runs across the step from the pharyngeal lines to the
    // oral fan (whose distances are measured from different origins), then projects back.
    {
        let pts: Vec<Vec2> = (0..N_LINES).map(|i| point_on(i, mean[i])).collect();
        let (mut xs, mut ys): (Vec<f64>, Vec<f64>) = (pts.iter().map(|p| p.x).collect(), pts.iter().map(|p| p.y).collect());
        smooth(&mut xs);
        smooth(&mut ys);
        for i in 0..N_LINES {
            let (o, d) = contour::line(i);
            mean[i] = (xs[i] - o.x) * d.x + (ys[i] - o.y) * d.y;
        }
        for j in 0..N_GUIDES {
            let (mut dx, mut dy): (Vec<f64>, Vec<f64>) = (0..N_LINES).map(|i| (loadings[i][j] * contour::line(i).1.x, loadings[i][j] * contour::line(i).1.y)).unzip();
            smooth(&mut dx);
            smooth(&mut dy);
            for i in 0..N_LINES {
                let d = contour::line(i).1;
                loadings[i][j] = dx[i] * d.x + dy[i] * d.y;
            }
        }
    }
    // how well the mean speaker (no per-speaker intercepts) fits every frame
    let (mut pe, mut pn) = (0.0, 0usize);
    for f in &frames {
        for i in 0..N_LINES {
            if f.s[i].is_finite() {
                let pred = mean[i] + (0..N_GUIDES).map(|j| loadings[i][j] * (f.guides[j] - g0[j])).sum::<f64>();
                pe += (f.s[i] - pred) * (f.s[i] - pred);
                pn += 1;
            }
        }
    }
    let pop_rms = (pe / pn as f64).sqrt();

    // ---- residual shape modes
    let mut cov = vec![vec![0.0; N_LINES]; N_LINES];
    for r in &resid {
        for i in 0..N_LINES {
            for j in 0..N_LINES {
                let (a, b) = (if r[i].is_finite() { r[i] } else { 0.0 }, if r[j].is_finite() { r[j] } else { 0.0 });
                cov[i][j] += a * b / frames.len() as f64;
            }
        }
    }
    let total: f64 = (0..N_LINES).map(|i| cov[i][i]).sum();
    let modes = eigen(cov, 3);

    // ---- walls: the speakers' means (chained as the tongue's), joined to the classic wall below
    // the MRI field and above the nasopharynx, and to the classic incisor
    let ys: Vec<f64> = (0..19).map(|i| 3.2 + 0.4 * i as f64).collect();
    let per: Vec<Vec<Option<f64>>> = ys.iter().map(|&y| walls.iter().map(|w| Some(x_at(w, y)).filter(|x| x.is_finite())).collect()).collect();
    let mut wx = vec![f64::NAN; ys.len()];
    chain(&per, &mut wx);
    let mut phar_wall: Vec<[f64; 2]> = vec![CLASSIC_WALL[0], CLASSIC_WALL[1]];
    for (y, x) in ys.iter().zip(&wx) {
        if x.is_finite() {
            phar_wall.push([round4(*x), round4(*y)]);
        }
    }
    phar_wall.push(CLASSIC_WALL[7]);
    phar_wall.push(CLASSIC_WALL[8]);
    let xs: Vec<f64> = (1..=19).map(|i| PALATE_START[0] + 0.25 * i as f64).collect();
    let per: Vec<Vec<Option<f64>>> = xs.iter().map(|&x| roofs.iter().map(|r| Some(y_at(r, x)).filter(|y| y.is_finite())).collect()).collect();
    let mut py = vec![f64::NAN; xs.len()];
    chain(&per, &mut py);
    let mut palate: Vec<[f64; 2]> = vec![PALATE_START];
    for (x, y) in xs.iter().zip(&py) {
        if y.is_finite() {
            palate.push([round4(*x), round4(*y)]);
        }
    }
    palate.extend_from_slice(&INCISOR);

    // ---- soft palate
    let len = median(&mut vel_len);
    let half = median(&mut vel_half);
    // The thickness stays the classic flap's (0.48 to 0.28 cm half-thickness). The outline's area
    // over its length (0.55 cm here) overstates it: the 10 mm slice blurs the edges, and the
    // levator's bulge on the nasal side adds area without thickening the oral surface. The
    // thicker flap also met the tongue in a nasalised /u/ (Neanderthal, port 0.96 cm²) and closed
    // the oral tract.
    let velum = VelumShape { length: round4(len), half_root: 0.48, half_tip: 0.28, angle_closed: round4(median(&mut ang_closed)), angle_open: round4(quantile(&mut ang_open, 0.9)) };

    // ---- report
    let mut classic: Vec<f64> = frames.iter().map(|f| f.classic_rms).collect();
    let classic_med = median(&mut classic);
    let rms_all = (resid.iter().flatten().filter(|x| x.is_finite()).map(|x| x * x).sum::<f64>() / resid.iter().flatten().filter(|x| x.is_finite()).count() as f64).sqrt();
    println!("{} frames from {} speakers; classic tongue fitted to each frame: median rms {} cm", frames.len(), n_sp, fixed(classic_med, 3));
    for j in 0..N_GUIDES {
        let mut xs: Vec<f64> = frames.iter().map(|f| f.guides[j]).collect();
        println!("guide {:>5}: {} .. {} .. {} (2/50/98%)", GUIDES[j], fixed(quantile(&mut xs.clone(), 0.02), 2), fixed(median(&mut xs.clone()), 2), fixed(quantile(&mut xs, 0.98), 2));
    }
    println!("line    n   mean    sd   rms  | {}", GUIDES.iter().map(|g| format!("{g:>7}")).collect::<String>());
    for i in 0..N_LINES {
        let name = if i < N_PHAR { format!("y{:.1}", contour::PHAR_Y[i]) } else { format!("{:.0}°", contour::ORAL_DEG[i - N_PHAR]) };
        println!("{:>5} {:>4} {:>6} {:>5} {:>5}  | {}", name, line_n[i], fixed(mean[i], 2), fixed(line_sd[i], 2), fixed(line_rms[i], 2), loadings[i].iter().map(|l| format!("{:>7}", fixed(*l, 3))).collect::<String>());
    }
    println!("residual rms {} cm within speakers, {} cm for the mean speaker; shape modes explain {} of the former", fixed(rms_all, 3), fixed(pop_rms, 3), modes.iter().map(|(l, _)| format!("{}%", fixed(100.0 * l / total, 0))).collect::<Vec<_>>().join(" + "));
    println!("velum: length {} cm, half-thickness {} cm, closed {}°, open {}° ({} closed / {} open frames)", fixed(velum.length, 2), fixed(half, 2), fixed(velum.angle_closed, 1), fixed(velum.angle_open, 1), ang_closed.len(), ang_open.len());

    let model = ContourModel {
        source: "Ruthven, Peplinski & Miquel (2023), A multi-speaker dataset of real-time two-dimensional speech magnetic resonance images with articulator ground-truth segmentations, doi:10.5281/zenodo.10046815, CC BY 4.0. Fitted by `chimera anatomy fit` from tools/contour-model/extract.py.".into(),
        mean: mean.iter().map(|x| round4(*x)).collect(),
        loadings: loadings.iter().map(|l| l.map(round4)).collect(),
        neutral: g0,
        guide_range: (0..N_GUIDES)
            .map(|j| {
                let mut xs: Vec<f64> = frames.iter().map(|f| f.guides[j]).collect();
                [round4(quantile(&mut xs.clone(), 0.02)), round4(quantile(&mut xs, 0.98))]
            })
            .collect(),
        modes: modes.iter().map(|(l, x)| x.iter().map(|a| round4(a * l.sqrt())).collect()).collect(),
        phar_wall,
        palate,
        velum,
        fit: json!({
            "frames": frames.len(),
            "speakers": n_sp,
            "classicFitRmsCm": round4(classic_med),
            "residualRmsCm": round4(rms_all),
            "meanSpeakerRmsCm": round4(pop_rms),
            "lineSdCm": line_sd.iter().map(|x| round4(*x)).collect::<Vec<_>>(),
            "lineRmsCm": line_rms.iter().map(|x| round4(*x)).collect::<Vec<_>>(),
            "lineFrames": line_n,
            "modeVarianceShare": modes.iter().map(|(l, _)| round4(l / total)).collect::<Vec<_>>(),
            "velumOutlineHalfThicknessCm": round4(half),
        }),
    };
    std::fs::write(&out, serde_json::to_string_pretty(&model).map_err(|e| e.to_string())? + "\n").map_err(|e| format!("{out}: {e}"))?;
    println!("wrote {out}");
    if let Some(path) = frames_out {
        let fr: Vec<Value> = frames.iter().map(|f| json!({ "speaker": f.speaker, "s": f.s.iter().map(|x| if x.is_finite() { json!(round4(*x)) } else { Value::Null }).collect::<Vec<_>>(), "guides": f.guides.map(round4), "classicRms": round4(f.classic_rms) })).collect();
        std::fs::write(&path, serde_json::to_string(&fr).map_err(|e| e.to_string())?).map_err(|e| format!("{path}: {e}"))?;
    }
    Ok(())
}

/// The mean over speakers of per-position values, chained: from the first position every speaker
/// has, each neighbour is the mean plus the mean change over the speakers present at both (at
/// least two), so a speaker dropping out doesn't step the mean. Positions no two speakers share
/// with a neighbour stay NaN.
fn chain(per: &[Vec<Option<f64>>], out: &mut [f64]) {
    let n = per.len();
    let full = (0..n).find(|&i| per[i].iter().all(Option::is_some)).or_else(|| (0..n).max_by_key(|&i| per[i].iter().filter(|x| x.is_some()).count())).unwrap_or(0);
    let avg = |xs: Vec<f64>| if xs.is_empty() { f64::NAN } else { xs.iter().sum::<f64>() / xs.len() as f64 };
    out[full] = avg(per[full].iter().flatten().copied().collect());
    let step = |out: &mut [f64], i: usize, j: usize| {
        let d: Vec<f64> = per[i].iter().zip(&per[j]).filter_map(|(a, b)| Some((*a)? - (*b)?)).collect();
        out[i] = if d.len() >= 2 && out[j].is_finite() { out[j] + avg(d) } else { f64::NAN };
    };
    for i in (0..full).rev() {
        step(out, i, i + 1);
    }
    for i in full + 1..n {
        step(out, i, i - 1);
    }
}

/// Two passes of a [1 2 1]/4 filter, ends kept.
fn smooth(x: &mut [f64]) {
    for _ in 0..2 {
        let y = x.to_vec();
        for i in 1..x.len().saturating_sub(1) {
            x[i] = 0.25 * y[i - 1] + 0.5 * y[i] + 0.25 * y[i + 1];
        }
    }
}

fn round4(x: f64) -> f64 {
    (x * 10000.0).round() / 10000.0
}
