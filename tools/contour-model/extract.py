"""Midsagittal contours from the speech MRI segmentations, registered into CHIMERA's head frame.

Data: Ruthven, Peplinski & Miquel (2023), "A multi-speaker dataset of real-time two-dimensional
speech magnetic resonance images with articulator ground-truth segmentations", Zenodo,
doi:10.5281/zenodo.10046815, CC BY 4.0. Five adults counting 1-10 in English, 10 fps, 1.17 mm pixels.
The data is not in the repository: download `data.zip` from Zenodo and pass its `data` folder.

Mask labels: 0 background, 1 head, 2 soft palate, 3 jaw (mandible with lower lip), 4 tongue,
5 vocal tract (airway), 6 tooth space.

Output (JSON, cm in the adult male body frame of `crates/chimera/src/anatomy/human.rs`: x forward,
y up, glottis at the origin): per speaker the static walls (hard palate, posterior pharyngeal wall)
and per frame the tongue outline, the soft palate outline, a jaw-opening estimate and the
velopharyngeal closure label. `chimera anatomy fit` turns it into the statistical contour model.

Registration, per speaker:
1. A similarity transform (rotation, uniform scale, translation) that puts two landmarks on the
   template's: the posterior nasal spine (where the oral roof meets the soft palate) and the lower
   edge of the upper lip (the front end of the oral roof). Both are medians over the speaker's
   frames. The scale normalises the speakers to the template's adult male size.
2. A bend of the pharynx: the speakers' necks lean by up to ~25 degrees against the palate (head
   and neck posture in the scanner), so everything below the velum is sheared horizontally until
   the posterior pharyngeal wall leans as the template's does. The shear fades out over 2 cm up to
   the velum and towards the front of the mouth, so the palate, teeth and lips stay where step 1
   put them. A shear keeps horizontal widths, which is what the pharyngeal grid measures.

usage: python extract.py <data dir> <out.json> [--plot dir]
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio
from skimage import measure

PIXEL_CM = 0.117
HEAD, VELUM, JAW, TONGUE, TRACT, TEETH = 1, 2, 3, 4, 5, 6

# the template's posterior pharyngeal wall leans back by 0.28 cm over 6 cm (p(-1.1, 1.5) → p(-1.38, 7.5))
WALL_LEAN_T = -0.28 / 6.0
# the bend's pivot height (cm, template frame) and the height over which it fades out below it;
# it also fades out towards the front, from x 3 to 5 cm
PIVOT_Y, BEND_FADE = 8.3, 2.0
FRONT_X0, FRONT_X1 = 3.0, 5.0

# template landmarks (adult male body cm, `HumanVocalTract::p` of the template points): where the
# oral roof meets the soft palate, the palate's first point p(1.0, 9.6) (the velum hinges at
# p(1.0, 9.75), 1.5 mm above, inside the tissue), and the upper lip's edge at rest (NEUTRAL lips,
# see `compute`)
PNS_T = np.array([0.5 + 0.5 * 0.86, 9.6])
LIP_T = np.array([0.5 + (8.15 + 0.12 * 0.5 - 0.5) * 0.86 + 0.2 * 0.95 - 0.15, 7.85 - 0.3 * 0.6 + 0.7 * 0.35])


def frame_files(root: Path, sub: int) -> list[Path]:
    fs = glob.glob(str(root / "GT_Segmentations" / f"Subject{sub}" / "mask_*.mat"))
    return [Path(p) for p in sorted(fs, key=lambda p: int(re.findall(r"mask_(\d+)\.mat$", p)[0]))]


def load(root: Path, sub: int) -> tuple[np.ndarray, list[int]]:
    files = frame_files(root, sub)
    nums = [int(re.findall(r"mask_(\d+)\.mat$", str(p))[0]) for p in files]
    return np.stack([sio.loadmat(p)["mask_frame"] for p in files]), nums


def closure_labels(root: Path) -> dict[int, dict[int, int]]:
    """{subject: {frame: 1 closed / 0 open}} from the velopharyngeal closure workbook."""
    try:
        import openpyxl
    except ImportError:
        return {}
    path = root / "Velopharyngeal_Closure" / "velopharyngeal_closure.xlsx"
    if not path.exists():
        return {}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: dict[int, dict[int, int]] = {}
    for ws in wb.worksheets:
        m = re.findall(r"(\d+)", ws.title)
        if not m:
            continue
        sub = int(m[0])
        # rows of (frame, closure); the first is the header
        out[sub] = {int(r[0]): int(r[1]) for r in ws.iter_rows(values_only=True) if isinstance(r[0], (int, float)) and r[1] in (0, 1)}
    return out


def to_cm(rc: np.ndarray) -> np.ndarray:
    """(row, col) pixel coordinates → (x forward, y up) cm; the faces look towards column 0."""
    rc = np.asarray(rc, float)
    return np.stack([-rc[..., 1] * PIXEL_CM, -rc[..., 0] * PIXEL_CM], -1)


def roof_profile(m: np.ndarray, c0: int, c1: int) -> dict[int, float]:
    """Row of the oral roof (head above the airway) per column c0..c1: the first pixel below the
    head that is airway, tongue, teeth or jaw."""
    out = {}
    for c in range(c0, c1 + 1):
        col = m[:, c]
        head = np.where(col == HEAD)[0]
        if len(head) == 0:
            continue
        below = np.where(np.isin(col, (TRACT, TONGUE, TEETH, JAW)) & (np.arange(len(col)) > head[0]))[0]
        if len(below):
            out[c] = below[0] - 0.5
    return out


def pns(m: np.ndarray) -> tuple[float, float] | None:
    """The posterior nasal spine: the front of the soft palate where it leaves the oral roof."""
    vel = np.argwhere(m == VELUM)
    if len(vel) == 0:
        return None
    c = vel[:, 1].min()  # the soft palate's frontmost column
    # the roof row there: the lowest head pixel just in front of the velum's root
    rows = vel[vel[:, 1] == c][:, 0]
    col = m[:, c - 1]
    head = np.where(col == HEAD)[0]
    below = np.where(np.isin(col, (TRACT, TONGUE)))[0]
    if len(below) == 0:
        return (float(rows.max()) + 0.5, c - 0.5)
    r = below[below > head[0]][0] - 0.5 if len(head) else below[0] - 0.5
    return (float(r), c - 0.5)


def lip_edge(m: np.ndarray) -> tuple[float, float] | None:
    """The lower edge of the upper lip: the frontmost airway pixel with head directly above it."""
    tr = np.argwhere(m == TRACT)
    if len(tr) == 0:
        return None
    best = None
    for r, c in tr:
        if r > 0 and m[r - 1, c] == HEAD:
            if best is None or c < best[1]:
                best = (r - 0.5, c)
    if best is None:
        return None
    return (float(best[0]), float(best[1]) - 0.5)


def wall_profile(m: np.ndarray, r0: int, r1: int) -> dict[int, float]:
    """Column of the posterior pharyngeal wall per row: the hindmost airway or velum pixel."""
    out = {}
    for r in range(r0, r1 + 1):
        cs = np.where(np.isin(m[r], (TRACT, VELUM)))[0]
        if len(cs) and m[r, min(cs.max() + 1, m.shape[1] - 1)] == HEAD:
            out[r] = cs.max() + 0.5
    return out


def outline(m: np.ndarray, label: int) -> np.ndarray | None:
    """The longest boundary of a label's region, as (row, col) points."""
    b = np.pad((m == label).astype(float), 1)
    cs = measure.find_contours(b, 0.5)
    if not cs:
        return None
    c = max(cs, key=len)
    return c - 1.0


def similarity(d1: np.ndarray, d2: np.ndarray, t1: np.ndarray, t2: np.ndarray):
    """z ↦ a·z + b (complex) taking d1 → t1 and d2 → t2."""
    zd1, zd2, zt1, zt2 = (complex(*p) for p in (d1, d2, t1, t2))
    a = (zt2 - zt1) / (zd2 - zd1)
    b = zt1 - a * zd1

    def f(p: np.ndarray) -> np.ndarray:
        z = p[..., 0] + 1j * p[..., 1]
        w = a * z + b
        return np.stack([w.real, w.imag], -1)

    return f, abs(a), np.degrees(np.angle(a))


def bend_for(wall: np.ndarray):
    """The pharynx bend (see the module notes) for a speaker's registered posterior wall points:
    a horizontal shear, so the pharynx's horizontal widths (what the grid measures) are kept."""
    sel = (wall[:, 1] > 3.5) & (wall[:, 1] < PIVOT_Y)
    b, _ = np.polyfit(wall[sel, 1], wall[sel, 0], 1)  # x = a + b·y
    lean = b - WALL_LEAN_T

    def f(p: np.ndarray) -> np.ndarray:
        p = np.asarray(p, float)
        u = np.clip((p[..., 1] - (PIVOT_Y - BEND_FADE)) / BEND_FADE, 0.0, 1.0)
        wy = 1.0 - u * u * (3 - 2 * u)  # 1 below the fade, 0 from the pivot up
        v = np.clip((p[..., 0] - FRONT_X0) / (FRONT_X1 - FRONT_X0), 0.0, 1.0)
        wx = 1.0 - v * v * (3 - 2 * v)  # the front of the mouth (teeth, lips, tongue tip) stays
        return np.stack([p[..., 0] + (PIVOT_Y - p[..., 1]) * lean * wy * wx, p[..., 1]], -1)

    return f, float(np.degrees(np.arctan(b) - np.arctan(WALL_LEAN_T)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path, help="the dataset's data folder (GT_Segmentations, ...)")
    ap.add_argument("out", type=Path)
    ap.add_argument("--plot", type=Path, default=None, help="write registration plots here")
    a = ap.parse_args(argv)
    labels = closure_labels(a.data)
    speakers = []
    for sub in range(1, 6):
        masks, nums = load(a.data, sub)
        # landmarks: medians over the frames
        p_rc = np.array([p for p in (pns(m) for m in masks) if p is not None])
        l_rc = np.array([p for p in (lip_edge(m) for m in masks) if p is not None])
        pns_rc, lip_rc = np.median(p_rc, 0), np.median(l_rc, 0)
        S, scale, rot = similarity(to_cm(pns_rc), to_cm(lip_rc), PNS_T, LIP_T)
        # static walls: per column / row medians over the frames
        c0, c1 = int(np.ceil(lip_rc[1])), int(np.floor(pns_rc[1]))
        roofs: dict[int, list[float]] = {}
        for m in masks:
            for c, r in roof_profile(m, c0, c1).items():
                roofs.setdefault(c, []).append(r)
        roof = np.array([[np.median(roofs[c]), c] for c in sorted(roofs, reverse=True) if len(roofs[c]) >= len(masks) // 2])
        tract_rows = np.where((masks == TRACT).any(0).any(1))[0]
        walls: dict[int, list[float]] = {}
        for m in masks:
            for r, c in wall_profile(m, int(tract_rows.min()), int(tract_rows.max())).items():
                walls.setdefault(r, []).append(c)
        wall = np.array([[r, np.median(walls[r])] for r in sorted(walls, reverse=True) if len(walls[r]) >= len(masks) // 2])
        B, turn = bend_for(S(to_cm(wall)))

        def T(p: np.ndarray) -> np.ndarray:
            return B(S(p))

        # the segmented field ends at a horizontal cut below the oropharynx: the lowest row with head
        cut_row = int(np.where((masks == HEAD).any(0).any(1))[0].max())
        frames = []
        for m, n in zip(masks, nums):
            t = outline(m, TONGUE)
            v = outline(m, VELUM)
            teeth = np.argwhere(m == TEETH)
            frames.append({
                "n": n,
                "tongue": np.round(T(to_cm(t)), 4).tolist() if t is not None else None,
                "velum": np.round(T(to_cm(v)), 4).tolist() if v is not None else None,
                # the lower incisors' top (tooth space is carried by the mandible)
                "teethTop": np.round(T(to_cm(teeth[teeth[:, 0].argmin()].astype(float))), 4).tolist() if len(teeth) else None,
                "closed": labels.get(sub, {}).get(n),
            })
        # the field's lower edge, as a line through two registered points (front, back)
        cut = T(to_cm(np.array([[cut_row + 0.5, c0], [cut_row + 0.5, wall[:, 1].max() + 2]])))
        speakers.append({
            "id": sub,
            "scale": round(float(scale), 4),
            "rotationDeg": round(float(rot), 2),
            "bendDeg": round(turn, 2),
            "cut": np.round(cut, 4).tolist(),
            "roof": np.round(T(to_cm(roof)), 4).tolist(),
            "pharWall": np.round(T(to_cm(wall)), 4).tolist(),
            "frames": frames,
        })
        print(f"subject {sub}: {len(frames)} frames, scale {scale:.3f}, rotation {rot:+.1f} deg, pharynx bend {turn:+.1f} deg, field ends at y {cut[0][1]:.2f}..{cut[1][1]:.2f} cm", file=sys.stderr)
    doc = {
        "source": "Ruthven, Peplinski & Miquel (2023), doi:10.5281/zenodo.10046815, CC BY 4.0; contours extracted and registered by tools/contour-model/extract.py",
        "frame": "adult male body cm (x forward, y up, glottis at the origin), human.rs",
        "pixelCm": PIXEL_CM,
        "landmarks": {"pns": PNS_T.round(4).tolist(), "lipEdge": LIP_T.round(4).tolist()},
        "speakers": speakers,
    }
    a.out.write_text(json.dumps(doc))
    if a.plot:
        plot(doc, a.plot)
    return 0


def plot(doc: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(16, 8))
    cols = ["C0", "C1", "C2", "C3", "C4"]
    for sp, col in zip(doc["speakers"], cols):
        r, w = np.array(sp["roof"]), np.array(sp["pharWall"])
        ax[0].plot(r[:, 0], r[:, 1], col, lw=2, label=f"S{sp['id']} roof/wall")
        ax[0].plot(w[:, 0], w[:, 1], col, lw=2)
        for f in sp["frames"][::6]:
            if f["tongue"]:
                t = np.array(f["tongue"])
                ax[1].plot(t[:, 0], t[:, 1], col, lw=0.6, alpha=0.6)
        ax[1].plot(r[:, 0], r[:, 1], col, lw=2)
        ax[1].plot(w[:, 0], w[:, 1], col, lw=2)
        c = np.array(sp["cut"])
        ax[1].plot(c[:, 0], c[:, 1], col, ls="--", lw=1)
    for a in ax:
        a.plot(*doc["landmarks"]["pns"], "k+", ms=14)
        a.plot(*doc["landmarks"]["lipEdge"], "k+", ms=14)
        a.set_aspect("equal")
        a.grid(alpha=0.3)
    ax[0].legend()
    ax[0].set_title("registered walls (template frame, cm)")
    ax[1].set_title("every 6th tongue outline")
    plt.tight_layout()
    plt.savefig(out / "registration.png", dpi=70)


if __name__ == "__main__":
    raise SystemExit(main())
