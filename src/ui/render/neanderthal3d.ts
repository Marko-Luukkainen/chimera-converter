/**
 * The Neanderthal's extras on the 3D head: a bushy, frizzy mop of hair and a beard (strands the
 * renderer sways and shakes each frame), and the stocky body he stands on (wireframe rings and
 * meridians, drawn in a frame that does not nod with the head).
 *
 * Body cm as in anatomy3d.ts: x forward, y up, z out of the right side of the face. Proportions
 * are a Neanderthal man's (about 165 cm): a barrel chest and a wide pelvis, broad shoulders,
 * short forearms and shins, big hands. Nothing here touches the sound.
 */

/** the head's surface, as anatomy3d's tabulated sections give it */
export interface HeadSurface {
  /** the lowest and highest heights of the head's outline (the neck's end, the crown) */
  y0: number;
  y1: number;
  /**
   * The surface on the right side (z ≥ 0) at height y, `th` round from the front midline (0) to
   * the back midline (π): the point, the section's centre and half-depth on the point's side
   * (front or back), and its half-width; null above and below the head.
   */
  at(y: number, th: number): { x: number; z: number; xw: number; hd: number; W: number } | null;
}

/** a strand of hair: points (flat xyz, rest pose), how free each is (0 at the root … 1 at the
 *  tip), how much of the jaw's turn it follows, and its own phase for the sway */
export interface Strand {
  a: Float32Array;
  hang: Float32Array;
  w: number;
  ph: number;
}

/** a line of the body: points (flat xyz) and how much of the breath each point takes */
export interface FigureLine {
  a: Float32Array;
  c: Float32Array;
}

export interface Figure {
  lines: FigureLine[];
  /** the trunk's axis (x) the chest swells about */
  cx: number;
  /** the soles and the crown (y) */
  bottom: number;
  top: number;
}

const PI = Math.PI;
const bump = (u: number) => (Math.abs(u) < 1 ? (1 - u * u) ** 2 : 0);
const smooth = (a: number, b: number, x: number) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};
type V3 = [number, number, number];
const norm = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

/** a small seeded generator, so the hair is the same every time the head is built */
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * One frizzy strand from a root on the scalp or the face: out along the surface normal, then
 * falling along `fall` as far as `droop`, curling round its own axis as it goes.
 */
function strand(root: V3, n: V3, fall: V3, len: number, droop: number, curl: number, turns: number, phase: number, steps: number): Float32Array {
  const up: V3 = Math.abs(n[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
  const u = norm(cross(up, n)), v = cross(n, u);
  const a = new Float32Array(3 * (steps + 1));
  for (let j = 0; j <= steps; j++) {
    const t = j / steps;
    const out = 0.12 * curl + len * 0.6 * t, down = len * droop * t * t;
    const r = curl * Math.pow(t, 0.7), an = 2 * PI * turns * t + phase;
    const cu = r * Math.cos(an), cv = r * Math.sin(an);
    for (let d = 0; d < 3; d++) a[3 * j + d] = root[d] + n[d] * out + fall[d] * down + u[d] * cu + v[d] * cv;
  }
  return a;
}

const hangOf = (steps: number, p: number) => {
  const h = new Float32Array(steps + 1);
  for (let j = 0; j <= steps; j++) h[j] = Math.pow(j / steps, p);
  return h;
};

/**
 * The hair and the beard. `templateY` maps a body height to the modern template's height (the
 * head's tables are by it); `jawW` is how much of the jaw's turn a point of the face follows; the
 * lips (their top and bottom heights and half-width) stay bare.
 */
export function neanderthalHair(head: HeadSurface, k: number, templateY: (y: number) => number, jawW: (x: number, y: number) => number, lips: { top: number; bottom: number; half: number }): { mane: Strand[]; beard: Strand[] } {
  const R = rng(1856); // the Feldhofer grotto
  const mane: Strand[] = [];
  const beard: Strand[] = [];
  // the scalp's normals: an ellipsoid round the braincase (a section's own outline would turn the
  // crown's hair sideways, as the sections shrink towards the top)
  const yc = head.y1 - 9 * k;
  const fr = head.at(yc, 0), bk = head.at(yc, PI), sd = head.at(yc, PI / 2);
  const xg = fr && bk ? (fr.x + bk.x) / 2 : 0, ea = fr && bk ? (fr.x - bk.x) / 2 : 10 * k, eb = head.y1 - yc, ec = sd ? sd.z : 7.5 * k;

  // ---- the mop: roots in rows down the scalp; the hairline leaves the brow ridge, the temples,
  // the ears and the face bare, and comes down the back to the nape
  const thMin = (Y: number) => (Y >= 18.6 ? 0 : Y >= 15.6 ? 0.42 * PI + ((18.6 - Y) / 3) * 0.13 * PI : Y >= 9 ? 0.72 * PI : Y >= 7.5 ? 0.72 * PI + ((9 - Y) / 1.5) * 0.28 * PI : Infinity);
  const STEPS = 10;
  for (let y = head.y1 - 0.3 * k; y > head.y0; y -= 0.72 * k) {
    const Y = templateY(y);
    const t0 = thMin(Y);
    if (!(t0 < PI)) continue;
    const mid = head.at(y, PI / 2);
    if (!mid) continue;
    const count = Math.max(2, Math.round(((PI - t0) / PI) * 15 * Math.min(1.2, mid.W / (6.5 * k))));
    for (const side of [1, -1]) {
      for (let i = 0; i < count; i++) {
        const th = Math.min(PI, t0 + ((i + 0.2 + 0.6 * R()) / count) * (PI - t0));
        if (side < 0 && th > PI - 0.02) continue; // the back midline once
        const yy = y + (R() - 0.5) * 0.6 * k;
        const s = head.at(yy, th);
        if (!s) continue;
        const root: V3 = [s.x, yy, side * s.z];
        const n = norm([(s.x - xg) / (ea * ea), (yy - yc) / (eb * eb), (side * s.z) / (ec * ec)]);
        const back = th / PI;
        const low = 1 - smooth(13, 19, Y); // the rows round the back and the nape hang longest
        const len = k * (4.6 + 2.8 * back + 2.4 * low + 1.8 * R());
        // a big, round mop: every strand first stands out from the scalp, then only the lower ones
        // at the sides and back fall, and none of them straight: wide, loose curls all the way
        const droop = 0.06 + 0.42 * back * (0.25 + 0.75 * low) + 0.08 * R();
        const fall: V3 = back < 0.3 ? norm([-0.7, -0.5, side * 0.2]) : norm([-0.3, -1, side * 0.3]);
        const curl = k * (0.55 + 0.45 * R()) * (0.8 + 0.06 * (len / k));
        mane.push({ a: strand(root, n, fall, len, droop, curl, 1.6 + 1.6 * R(), 2 * PI * R(), STEPS), hang: hangOf(STEPS, 1.2), w: 0, ph: 2 * PI * R() });
      }
    }
  }

  // ---- the beard: the chin, the jaw and the cheeks below the cheekbones, round to the sideburns;
  // the lips and a margin round them stay bare
  const B_STEPS = 7;
  for (let y = head.y0 + 0.6 * k; y < head.y1; y += 0.7 * k) {
    const Y = templateY(y);
    if (Y < 2.6) continue;
    if (Y > 15.2) break;
    // above the mouth's corners only the sides grow it; above the cheeks, only the sideburns
    const thLo = Y > 9.6 ? 0.44 * PI : Y > 6.0 ? 0.16 * PI : 0;
    const thHi = Y > 9.6 ? 0.52 * PI : 0.6 * PI;
    const count = Y > 9.6 ? 1 : 7;
    for (const side of [1, -1]) {
      for (let i = 0; i < count; i++) {
        const th = thLo + ((i + 0.15 + 0.7 * R()) / count) * (thHi - thLo);
        if (side < 0 && th < 0.02) continue; // the front midline once
        const yy = y + (R() - 0.5) * 0.5 * k;
        const s = head.at(yy, th);
        if (!s) continue;
        if (yy > lips.bottom - 0.9 * k && yy < lips.top + 0.6 * k && s.z < lips.half + 0.9 * k && s.x > s.xw) continue;
        const root: V3 = [s.x, yy, side * s.z];
        const hd = Math.max(0.5 * k, s.hd);
        const n = norm([(s.x - s.xw) / (hd * hd), -0.09 / k, (side * s.z) / (s.W * s.W)]);
        const chin = bump(th / (0.32 * PI)) * (1 - smooth(4.5, 7, Y));
        const sideburn = Y > 9.6 ? 1 : 0;
        const len = k * (sideburn ? 2.2 + 1.2 * R() : 2.8 + 2.2 * R() + 4.0 * chin);
        const fall = norm([0.25, -1, side * 0.1]);
        const curl = k * (0.32 + 0.3 * R());
        beard.push({ a: strand(root, n, fall, len, 0.75 + 0.15 * R(), curl, 1.1 + 1.4 * R(), 2 * PI * R(), B_STEPS), hang: hangOf(B_STEPS, 1.4), w: jawW(root[0], root[1]), ph: 2 * PI * R() });
      }
    }
  }
  return { mane, beard };
}

/** a trunk section: height above the soles (cm), half-width, half-depth, forward shift, squareness */
type TrunkRow = readonly [number, number, number, number, number];
/** a limb section: height above the soles (cm), centre's distance out from the midline (z),
 *  forward shift (x), half-width (z), half-depth (x) */
type LimbRow = readonly [number, number, number, number, number];

// a Neanderthal man of 165 cm (scaled with the head): the neck's end is at 139 cm
const NECK_H = 139, HEIGHT = 165;
const TRUNK: readonly TrunkRow[] = [
  [137.5, 9.8, 6.2, 0.2, 2.4],
  [136, 15.5, 7.6, 0.2, 2.6], // the trapezius' slope
  [134.3, 20.5, 9.4, 0.0, 2.8],
  [132, 22.8, 11.0, -0.4, 3.0], // broad shoulders, the deltoids
  [129.5, 21.6, 12.3, -0.4, 3.0],
  [127, 17.8, 13.2, -0.2, 2.6], // the armpits: the trunk alone below
  [122, 17.8, 13.9, 0.4, 2.5], // a barrel chest
  [116, 17.3, 13.5, 0.6, 2.4],
  [110, 16.5, 12.5, 0.4, 2.3],
  [104, 16.1, 11.7, 0.4, 2.2],
  [98, 17.1, 11.8, 0.0, 2.3], // a wide pelvis
  [91, 18.3, 12.2, -0.6, 2.4],
  [83, 17.8, 12.4, -1.6, 2.4],
  [76, 15.8, 10.8, -1.2, 2.2],
];
const LEG: readonly LimbRow[] = [
  [78, 9.0, -0.4, 9.2, 9.8], // thick thighs
  [68, 9.3, 0.4, 8.4, 9.0],
  [58, 9.6, 0.9, 7.3, 7.9],
  [50, 9.8, 1.2, 6.2, 6.6],
  [44, 10.0, 1.4, 5.5, 5.9], // the knee: short shins below
  [38, 10.1, 0.4, 5.7, 6.4],
  [31, 10.2, -0.4, 6.1, 6.8],
  [23, 10.3, 0.0, 4.8, 5.4],
  [15, 10.4, 0.4, 3.8, 4.2],
  [9, 10.5, 0.6, 3.5, 3.7],
];
const ARM: readonly LimbRow[] = [
  [131.5, 20.0, -0.2, 5.6, 5.8],
  [124, 23.4, -0.6, 5.4, 5.6], // hanging clear of the barrel chest
  [116, 23.6, -1.0, 5.0, 5.2],
  [108, 23.4, -1.0, 4.4, 4.6], // the elbow
  [104, 23.0, -0.4, 4.2, 4.4],
  [98, 23.2, 0.8, 4.4, 4.6], // short, thick forearms
  [92, 23.4, 2.0, 3.8, 4.0],
  [86, 23.0, 3.0, 3.0, 3.4],
];

function lerpRow<T extends readonly number[]>(rows: readonly T[], h: number): number[] {
  if (h >= rows[0][0]) return [...rows[0]];
  for (let i = 1; i < rows.length; i++) {
    if (h >= rows[i][0]) {
      const a = rows[i - 1], b = rows[i], t = (h - b[0]) / (a[0] - b[0]);
      return a.map((x, j) => b[j] + (x - b[j]) * t);
    }
  }
  return [...rows[rows.length - 1]];
}

/**
 * The standing body under the head: the neck's end (its centre, half-depth and half-width) is
 * where the head's own neck stops, so the two meet.
 */
export function standingBody(neck: { y: number; x: number; hd: number; hw: number }, k: number): Figure {
  const u = k / 1.06; // cm of the figure per cm of a Neanderthal's
  const sole = neck.y - NECK_H * u;
  const Y = (h: number) => sole + h * u;
  const cx = neck.x;
  const breath = (h: number) => bump((h - 119) / 15);
  const lines: FigureLine[] = [];
  const push = (pts: number[], c: number[]) => {
    if (pts.length >= 6) lines.push({ a: new Float32Array(pts), c: new Float32Array(c) });
  };
  // the trunk: the neck's end first, so it meets the head
  const trunk: TrunkRow[] = [[NECK_H, neck.hw / u, neck.hd / u, 0, 2.2], ...TRUNK];
  const trunkAt = (h: number, an: number): V3 => {
    const [, hw, hd, xo, e] = lerpRow(trunk, h);
    const c = Math.cos(an), s = Math.sin(an);
    return [cx + (xo + hd * Math.sign(c) * Math.pow(Math.abs(c), 2 / e)) * u, Y(h), hw * Math.sign(s) * Math.pow(Math.abs(s), 2 / e) * u];
  };
  for (let h = NECK_H - 1.5; h >= 76; h -= 3.5) {
    const pts: number[] = [], c: number[] = [];
    for (let i = 0; i <= 40; i++) {
      pts.push(...trunkAt(h, (i / 40) * 2 * PI));
      c.push(breath(h));
    }
    push(pts, c);
  }
  for (let m = 0; m < 12; m++) {
    const an = (m / 12) * 2 * PI, pts: number[] = [], c: number[] = [];
    for (let h = NECK_H; h >= 76; h -= 2) {
      pts.push(...trunkAt(h, an));
      c.push(breath(h));
    }
    push(pts, c);
  }
  // the collarbones and the nipples, so the front reads as a front
  for (const side of [1, -1]) {
    const pts: number[] = [];
    for (let i = 0; i <= 10; i++) {
      const t = i / 10, h = 133.6 + 1.2 * Math.sin(PI * t);
      const [x, y, z] = trunkAt(h, (side * PI) / 2 * (0.1 + 0.62 * t));
      pts.push(x + 0.3 * u, y, z);
    }
    push(pts, new Array(11).fill(breath(133.6)));
    const [x, y, z] = trunkAt(121, side * 0.42);
    const ring: number[] = [];
    for (let i = 0; i <= 12; i++) ring.push(x + 0.25 * u, y + 1.1 * u * Math.sin((i / 12) * 2 * PI), z + 1.1 * u * Math.cos((i / 12) * 2 * PI));
    push(ring, new Array(13).fill(breath(121)));
  }

  // limbs: horizontal rings along the limb, and a few lines down it
  const limb = (rows: readonly LimbRow[], side: number, step: number) => {
    const top = rows[0][0], end = rows[rows.length - 1][0];
    const at = (h: number, an: number): V3 => {
      const [, zc, xo, hw, hd] = lerpRow(rows, h);
      return [cx + (xo + hd * Math.cos(an)) * u, Y(h), side * (zc + hw * Math.sin(an)) * u];
    };
    for (let h = top - 1; h >= end; h -= step) {
      const pts: number[] = [];
      for (let i = 0; i <= 20; i++) pts.push(...at(h, (i / 20) * 2 * PI));
      push(pts, new Array(21).fill(0));
    }
    for (let m = 0; m < 6; m++) {
      const pts: number[] = [];
      for (let h = top; h >= end; h -= 2) pts.push(...at(h, (m / 6) * 2 * PI));
      push(pts, new Array(pts.length / 3).fill(0));
    }
    return at;
  };
  for (const side of [1, -1]) {
    limb(LEG, side, 3.5);
    limb(ARM, side, 3.5);
    // the hand, palm to the thigh: a broad palm, four thick fingers and the thumb
    const wz = 23.0 * side, wx = 3.0;
    const palm = (h: number, half: number, thick: number) => {
      const pts: number[] = [];
      for (let i = 0; i <= 16; i++) {
        const an = (i / 16) * 2 * PI;
        pts.push(cx + (wx + half * Math.cos(an)) * u, Y(h), (wz + thick * side * Math.sin(an) - 0.3 * side) * u);
      }
      push(pts, new Array(17).fill(0));
    };
    palm(84, 3.6, 1.5);
    palm(80, 4.6, 1.6);
    palm(76.5, 4.7, 1.4);
    for (let f = 0; f < 4; f++) {
      const fx = wx + (-3.3 + 2.2 * f), len = f === 1 ? 9 : f === 0 ? 7 : 8;
      const pts: number[] = [];
      for (let j = 0; j <= 5; j++) {
        const t = j / 5;
        // the fingers hang, curling a little in towards the thigh
        pts.push(cx + fx * u, Y(76.5 - len * t), (wz - side * (0.3 + 1.2 * t * t)) * u);
      }
      push(pts, new Array(6).fill(0));
    }
    const th: number[] = [];
    for (let j = 0; j <= 5; j++) {
      const t = j / 5;
      th.push(cx + (wx + 4.2 + 1.8 * t) * u, Y(82 - 7 * t), (wz - side * (0.6 + 1.0 * t)) * u);
    }
    push(th, new Array(6).fill(0));
    // the foot: the sole's outline, the ankle down to the toes, and the toes
    const az = 10.5 * side, ax = 0.6;
    const foot: number[] = [];
    const outline: [number, number][] = [[-5.5, 0], [-4.8, 2.9], [-1, 3.3], [6, 3.8], [13, 4.6], [17.5, 4.4], [20, 2.4], [20.5, 0], [20, -2.2], [17, -3.6], [10, -3.0], [3, -2.6], [-2, -2.8], [-4.8, -2.6], [-5.5, 0]];
    for (const [x, z] of outline) foot.push(cx + (ax + x) * u, Y(0.4), (az + side * z) * u);
    push(foot, new Array(outline.length).fill(0));
    for (const [x0, z0, x1, h1] of [[0.6, 0, 16, 2.6], [0.6, 3.2, 13, 2.2], [0.6, -3.2, 12, 2.0], [-4.8, 0, -4.8, 6.5]] as const) {
      const pts: number[] = [];
      for (let j = 0; j <= 6; j++) {
        const t = j / 6;
        pts.push(cx + (ax + x0 + (x1 - x0) * t) * u, Y(9 - (9 - h1) * Math.sqrt(t)), (az + side * z0 * (1 - 0.3 * t)) * u);
      }
      push(pts, new Array(7).fill(0));
    }
    for (let toe = 0; toe < 5; toe++) {
      // the big toe on the inside and furthest forward, the little toe outside and back
      const tz = -3.0 + 1.6 * toe, tx = 19.6 - 0.35 * toe * toe;
      const ring: number[] = [];
      for (let i = 0; i <= 10; i++) {
        const an = (i / 10) * 2 * PI;
        ring.push(cx + (ax + tx - 1.2 + 1.2 * Math.cos(an)) * u, Y(1.4 + 0.9 * Math.sin(an)), (az + side * (tz + 0.2 * Math.sin(an))) * u);
      }
      push(ring, new Array(11).fill(0));
    }
  }
  return { lines, cx, bottom: sole, top: neck.y + (HEIGHT - NECK_H) * u };
}
