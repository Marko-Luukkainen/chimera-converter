//! Statistical contour model of the tongue and the fixed walls, fitted to speech MRI.
//!
//! The hand-built anatomy (`human.rs`, [`TractModel::Classic`]) draws the tongue as a circle with
//! a root curve and a blade, over hand-placed walls. [`TractModel::Contour`] takes the tongue's
//! back and dorsum, the posterior pharyngeal wall, the hard palate and the soft palate's shape from
//! real midsagittal MRI instead, as a linear model in the style of Maeda's (1990) guided factor
//! analysis: the tongue surface is where it crosses a fixed fan of measuring lines, and its
//! distance along each line is a mean plus a linear function of the articulators the rest of the
//! engine already drives (jaw, tongue-body centre, tongue root).
//!
//! The guides are the classic model's own controls, measured on every MRI frame: the jaw opening
//! (the lower incisors' drop), the tongue-body centre (the centre of the classic tongue's circle
//! fitted to the dorsum) and the root (its position below the dorsum, beyond what the body's
//! position predicts). The planner and the gestures keep working unchanged, and the MRI decides
//! how the real tongue's shape follows them; the vowels have their own calibration for this
//! anatomy. The tongue tip, blade, lips, teeth, jaw kinematics and larynx stay the classic model's.
//!
//! `contourModel.generated.json` is written by `chimera anatomy fit` from the contours that
//! `tools/contour-model/extract.py` takes out of Ruthven, Peplinski & Miquel (2023), "A
//! multi-speaker dataset of real-time two-dimensional speech magnetic resonance images with
//! articulator ground-truth segmentations", doi:10.5281/zenodo.10046815, CC BY 4.0.
//!
//! All coordinates here are the adult male body frame (cm; x forward, y up, glottis at the
//! origin): `HumanVocalTract::p` of the template with scale 1. Other bodies map them through
//! their own `p`, as the classic landmarks are.
//!
//! [`TractModel::Classic`]: super::human::TractModel::Classic
//! [`TractModel::Contour`]: super::human::TractModel::Contour

use super::geom::{Polyline, Vec2, add, ray_polyline, scale, v};
use super::human::{HumanArtic, NEUTRAL};
use crate::math::{PI, cos, sin};
use serde::{Deserialize, Serialize};
use std::sync::LazyLock;

/// Heights (cm) of the horizontal lines across the lower pharynx; below the lowest the tongue root
/// is the classic curve from the vallecula (the MRI field ends above it for some speakers).
pub const PHAR_Y: [f64; 6] = [4.0, 4.5, 5.0, 5.5, 6.0, 6.5];
/// Where the pharyngeal lines start (cm, in front of the tongue root, looking back).
pub const PHAR_X0: f64 = 4.0;
/// The oral lines' centre: the classic grid's mid-oral centre p(2.6, 6.95).
pub const ORAL_C: Vec2 = v(0.5 + (2.6 - 0.5) * 0.86, 6.95);
/// The oral lines' angles (degrees, from straight back over the top to forward-up). The last one
/// meets the front of the dorsum; from there to the tip runs the classic blade.
pub const ORAL_DEG: [f64; 15] = [180.0, 170.0, 160.0, 150.0, 140.0, 130.0, 120.0, 110.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0];
pub const N_PHAR: usize = PHAR_Y.len();
pub const N_LINES: usize = PHAR_Y.len() + ORAL_DEG.len();
/// The guides, in this order: jaw, tbX, tbY, root (`HumanArtic` units).
pub const GUIDES: [&str; 4] = ["jaw", "tbX", "tbY", "root"];
pub const N_GUIDES: usize = GUIDES.len();

/// Line `i`: origin and unit direction (adult male body cm).
pub fn line(i: usize) -> (Vec2, Vec2) {
    if i < N_PHAR {
        (v(PHAR_X0, PHAR_Y[i]), v(-1.0, 0.0))
    } else {
        let a = ORAL_DEG[i - N_PHAR] * (PI / 180.0);
        (ORAL_C, v(cos(a), sin(a)))
    }
}

/// The point at distance `s` along line `i`.
#[inline]
pub fn point(i: usize, s: f64) -> Vec2 {
    let (p, d) = line(i);
    add(p, scale(d, s))
}

/// The tongue's distance from the oral lines' centre at any angle between the first and last
/// oral line (degrees), a Catmull-Rom spline through the lines' distances (they are 10° apart).
pub fn oral_distance(s: &[f64; N_LINES], deg: f64) -> f64 {
    let o = &s[N_PHAR..];
    let n = o.len();
    let u = ((ORAL_DEG[0] - deg) / (ORAL_DEG[0] - ORAL_DEG[1])).clamp(0.0, (n - 1) as f64);
    let j = (u.floor() as usize).min(n - 2);
    let t = u - j as f64;
    let (p0, p1, p2, p3) = (o[j.saturating_sub(1)], o[j], o[j + 1], o[(j + 2).min(n - 1)]);
    let (t2, t3) = (t * t, t * t * t);
    0.5 * (2.0 * p1 + (-p0 + p2) * t + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2 + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3)
}

/// The guides of an articulation.
#[inline]
pub fn guides(a: &HumanArtic) -> [f64; N_GUIDES] {
    [a.jaw, a.tb_x, a.tb_y, a.root]
}

/// Where each line leaves a closed outline for the last time (its distance along the line from
/// the origin, searched over −4..9 cm), or NaN where it misses. `buf` holds the crossings.
pub fn measure(outline: &Polyline, out: &mut [f64; N_LINES], buf: &mut [f64]) {
    for (i, o) in out.iter_mut().enumerate() {
        let (p, d) = line(i);
        let n = ray_polyline(p.x, p.y, d.x, d.y, outline, -4.0, 9.0, buf);
        let mut best = f64::NAN;
        for &t in &buf[..n] {
            if !(t <= best) {
                best = t;
            }
        }
        *o = best;
    }
}

/// The soft palate's shape: the classic flap from the posterior nasal spine with the MRI's length
/// and swing (its thickness stays the classic one; see `chimera anatomy fit`).
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VelumShape {
    /// hinge to uvula tip (cm)
    pub length: f64,
    /// half-thickness at the hinge and at the tip (cm)
    pub half_root: f64,
    pub half_tip: f64,
    /// direction of the flap closed (port 0) and open (port 1.2 cm²), degrees (180 = straight back)
    pub angle_closed: f64,
    pub angle_open: f64,
}

/// The fitted model (`contourModel.generated.json`).
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContourModel {
    pub source: String,
    /// distance of the tongue surface along each line at the neutral articulation (cm)
    pub mean: Vec<f64>,
    /// ∂distance/∂guide per line (cm per guide unit), guides in [`GUIDES`] order
    pub loadings: Vec<[f64; N_GUIDES]>,
    /// the guides' values the mean is taken at ([`NEUTRAL`]'s)
    pub neutral: [f64; N_GUIDES],
    /// the guides' range in the MRI frames (2nd and 98th percentiles): the model is a fit
    /// inside it and an extrapolation outside
    #[serde(default)]
    pub guide_range: Vec<[f64; 2]>,
    /// residual shape modes (per line, cm per standard deviation), largest first; not driven yet
    #[serde(default)]
    pub modes: Vec<Vec<f64>>,
    /// posterior pharyngeal wall, bottom to top (control points, cm)
    pub phar_wall: Vec<[f64; 2]>,
    /// hard palate's oral surface, the soft palate's root to the upper incisor edge (control points, cm)
    pub palate: Vec<[f64; 2]>,
    pub velum: VelumShape,
    /// fit statistics, for the record
    #[serde(default)]
    pub fit: serde_json::Value,
}

impl ContourModel {
    /// The tongue surface's distance along each line for an articulation (cm).
    pub fn distances(&self, a: &HumanArtic, out: &mut [f64; N_LINES]) {
        let g = guides(a);
        for (i, o) in out.iter_mut().enumerate() {
            let mut s = self.mean[i];
            for j in 0..N_GUIDES {
                s += self.loadings[i][j] * (g[j] - self.neutral[j]);
            }
            *o = s;
        }
    }

    /// The tongue surface on each line for an articulation (adult male body cm).
    pub fn tongue(&self, a: &HumanArtic, out: &mut [Vec2; N_LINES]) {
        let mut s = [0.0; N_LINES];
        self.distances(a, &mut s);
        for (i, o) in out.iter_mut().enumerate() {
            *o = point(i, s[i]);
        }
    }

    pub fn phar_wall_points(&self) -> Vec<Vec2> {
        self.phar_wall.iter().map(|p| v(p[0], p[1])).collect()
    }

    pub fn palate_points(&self) -> Vec<Vec2> {
        self.palate.iter().map(|p| v(p[0], p[1])).collect()
    }
}

static MODEL: LazyLock<ContourModel> = LazyLock::new(|| serde_json::from_str(include_str!("contourModel.generated.json")).expect("contourModel.generated.json"));

/// The embedded model (parsed once).
pub fn model() -> &'static ContourModel {
    &MODEL
}

/// Parse the model now (so nothing initialises lazily on the audio thread).
pub fn init() {
    LazyLock::force(&MODEL);
}

/// Neutral guides, for the fit.
pub fn neutral_guides() -> [f64; N_GUIDES] {
    guides(&NEUTRAL)
}
