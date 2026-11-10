# contour-model

Builds CHIMERA's second anatomy, the **statistical contour model** (`TractModel::Contour`,
`crates/chimera/src/anatomy/contour.rs`), from real speech MRI. In the app it is the **MRI**
choice next to the body; on the command line a body name with `/contour` (`male/contour`).

```
MRI segmentations ─► extract.py ─► contours.json ─► chimera anatomy fit ─► contourModel.generated.json
 (5 speakers,         (outlines,      (registered      (guided linear model,     (embedded in the engine)
  392 frames)          landmarks)      to the head      walls, soft palate)
                                       frame)                                  ─► chimera calibrate vowels --contour
```

## What comes from the MRI

| Part | Classic anatomy | Contour anatomy |
|---|---|---|
| Tongue back and dorsum | circle + root curve | MRI model: mean shape + how it moves with jaw, tongue body and root |
| Posterior pharyngeal wall | hand-placed points | speakers' mean (classic below the MRI field and in the nasopharynx) |
| Hard palate | hand-placed points | speakers' mean (classic incisor edge, so teeth and lips stay put) |
| Soft palate | 2.8 cm flap, 194°–240° | MRI length and closed/open directions (classic thickness) |
| Tongue tip and blade, lips, teeth, jaw, larynx, epilarynx | classic | classic |
| Vowel targets | `vowelTargets*.generated.json` | `vowelTargets*.contour.generated.json` |
| Consonant targets | calibrated | the classic ones |

The model follows Maeda's (1990) guided factor analysis. The tongue surface is measured on 21 fixed
lines (six horizontals across the lower pharynx, 15 rays from the mid-oral centre), and its distance
along each line is a mean plus a linear function of four *guides*: the jaw opening, the tongue-body
centre (x, y) and the tongue root. These are the engine's own articulators, measured on every MRI
frame (jaw: the lower incisors' drop; body: the centre of a 2.25 cm circle fitted to the dorsum;
root: its position on the 5.5 cm line beyond what the body's position predicts). The planner,
the gestures and the UI keep driving the same controls; the MRI decides how the tongue's shape
follows them. The loadings come from a regression pooled within speakers (one intercept per
speaker), so differences between people don't pass for articulation; the mean is the mean speaker.

## Running it

The data is not in the repository. Download `data.zip` (22 MB) from
<https://zenodo.org/records/10046815> and unzip it.

```
python tools/contour-model/extract.py <unzipped>/data contours.json --plot plots
cargo run --release -p chimera-cli -- anatomy fit contours.json --frames frames.json
cargo run --release -p chimera-cli -- calibrate vowels all --contour
cargo run --release -p chimera-cli -- calibrate vowels all --fi --contour
cargo run --release -p chimera-cli -- anatomy frame female/contour i > frame.json
```

The app's switch has its own browser test: `bun run build && bun run preview`, then
`bun tools/e2e-anatomy.ts`.

`extract.py` needs numpy, scipy, scikit-image and openpyxl. `anatomy fit` prints each line's fit
and the guides' ranges; `anatomy frame` prints a posture's geometry as JSON.

### Registration

Per speaker, a similarity transform puts the oral roof's meeting with the soft palate on the
palate's first point, p(1.0, 9.6), and the lower edge of the upper lip on the template's upper lip
at rest. The scale (0.96–1.07) normalises the speakers to the adult male template. The speakers'
necks lean by 4–24° against the palate (posture in the scanner), so below the velum each speaker is
sheared horizontally until the posterior pharyngeal wall leans as the template's does; the shear
fades out towards the velum and the front of the mouth. The MRI field ends 2–5 cm above the glottis
depending on the speaker, so measurements within 3 mm of its edge are dropped and the means over
speakers are chained from the lines every speaker reaches.

## Fit (as generated)

- 392 frames, 5 speakers; the counting covers /ʌ u i ɔ aɪ ɪ ɛ eɪ/ and many consonants, but no
  fully open vowel, so /ɑ a/ are a mild extrapolation.
- Residual 1.7 mm rms within speakers (the pixels are 1.17 mm), 3.1 mm for the mean speaker.
  For comparison the classic tongue, fitted freely to each frame, misses by 3.2 mm (median).
- Soft palate: 2.81 cm long, 204° closed, 234° open. Its outline's area over its length says
  1.1 cm thick, which the 10 mm slice and the levator's bulge overstate; the flap keeps the
  classic thickness.

## Licence of the data

Ruthven, M., Peplinski, A. M., & Miquel, M. E. (2023). *A multi-speaker dataset of real-time
two-dimensional speech magnetic resonance images with articulator ground-truth segmentations*
(v2). Zenodo. <https://doi.org/10.5281/zenodo.10046815>. Licensed CC BY 4.0
(<https://creativecommons.org/licenses/by/4.0/>). `contourModel.generated.json` is derived from
it (contours extracted, registered and reduced to a linear model); no images or masks are in this
repository.
