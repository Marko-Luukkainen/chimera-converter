/**
 * Note edits that keep a melody singable by Chimera: every syllable starts exactly one note, in
 * order, and the notes after it until the next syllable are melisma (`syl: null`, the vowel held
 * onto a new pitch). Each edit returns a new list, or null when it would break that.
 */

export interface Note {
  start: number;
  end: number;
  midi: number;
  /** the syllable this note starts, or null for a melisma note */
  syl: number | null;
}

/** shortest note an edit may leave (s) */
export const MIN_DUR = 0.05;
/** notes this close count as touching (legato): moving one edge moves the other */
const TOUCH = 0.005;

const copy = (ns: Note[]): Note[] => ns.map((n) => ({ ...n }));

/** the syllable each note sings (its own, or the head's before it) */
export function syllableOf(ns: Note[]): number[] {
  let h = -1;
  return ns.map((n) => (n.syl !== null ? (h = n.syl) : h));
}

/** heads 0..n-1 in order, the first note a head, no overlaps or empty notes */
export function valid(ns: Note[], nSyl: number): boolean {
  const heads = ns.filter((n) => n.syl !== null).map((n) => n.syl);
  if (heads.length !== nSyl || heads.some((h, i) => h !== i)) return false;
  if (ns.length && ns[0].syl === null) return false;
  for (let i = 0; i < ns.length; i++) {
    if (ns[i].end - ns[i].start < MIN_DUR - 1e-9) return false;
    if (i && ns[i].start < ns[i - 1].end - 1e-6) return false;
  }
  return true;
}

export function setPitch(ns: Note[], i: number, midi: number): Note[] {
  const out = copy(ns);
  out[i].midi = Math.max(24, Math.min(96, midi));
  return out;
}

/** Move one edge of note i to t, as far as its neighbours and MIN_DUR allow; a touching
 * neighbour's edge moves with it. */
export function moveEdge(ns: Note[], i: number, edge: "start" | "end", t: number): Note[] {
  const out = copy(ns);
  const n = out[i];
  if (edge === "start") {
    const prev = out[i - 1];
    const touching = prev && Math.abs(prev.end - n.start) < TOUCH;
    const lo = prev ? (touching ? prev.start + MIN_DUR : prev.end) : 0;
    n.start = Math.max(lo, Math.min(t, n.end - MIN_DUR));
    if (touching) prev.end = n.start;
  } else {
    const next = out[i + 1];
    const touching = next && Math.abs(next.start - n.end) < TOUCH;
    const hi = next ? (touching ? next.end - MIN_DUR : next.start) : Infinity;
    n.end = Math.min(hi, Math.max(t, n.start + MIN_DUR));
    if (touching) next.start = n.end;
  }
  return out;
}

/** Move a whole note in time (keeping its length) between its neighbours. */
export function moveNote(ns: Note[], i: number, dt: number): Note[] {
  const out = copy(ns);
  const n = out[i];
  const lo = i > 0 ? out[i - 1].end : 0;
  const hi = i + 1 < out.length ? out[i + 1].start : Infinity;
  const d = Math.max(lo - n.start, Math.min(dt, hi - n.end));
  n.start += d;
  n.end += d;
  return out;
}

/** Split note i at t: the second half holds the same syllable's vowel (a melisma note). */
export function split(ns: Note[], i: number, t: number): Note[] | null {
  const n = ns[i];
  if (t - n.start < MIN_DUR || n.end - t < MIN_DUR) return null;
  const out = copy(ns);
  out[i].end = t;
  out.splice(i + 1, 0, { start: t, end: n.end, midi: n.midi, syl: null });
  return out;
}

/** Fold melisma note i into the note before it. */
export function mergePrev(ns: Note[], i: number): Note[] | null {
  if (i <= 0 || ns[i].syl !== null) return null;
  const out = copy(ns);
  out[i - 1].end = out[i].end;
  out.splice(i, 1);
  return out;
}

/** Move the syllable that note i starts one note earlier (-1) or later (+1). Earlier: the note
 * before must be a melisma note (it starts the syllable, note i holds it). Later: the note after
 * must hold this syllable (it starts it, note i goes to the syllable before). */
export function shiftSyllable(ns: Note[], i: number, dir: -1 | 1): Note[] | null {
  const k = ns[i].syl;
  if (k === null) return null;
  const j = i + dir;
  if (j < 0 || j >= ns.length || ns[j].syl !== null) return null;
  if (dir === 1 && i === 0) return null; // the first note must start a syllable
  const out = copy(ns);
  out[j].syl = k;
  out[i].syl = null;
  return out;
}

/** melisma notes Chimera can't sing: the held syllable isn't its word's last (its melisma mark
 * goes between words); the server folds them into the note before */
export function innerMelismas(ns: Note[], sylWord: [number, number][], sylsPerWord: number[]): Set<number> {
  const bad = new Set<number>();
  const of = syllableOf(ns);
  ns.forEach((n, i) => {
    if (n.syl !== null || of[i] < 0) return;
    const [w, s] = sylWord[of[i]];
    if (s < sylsPerWord[w] - 1) bad.add(i);
  });
  return bad;
}

export const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const noteName = (m: number): string => `${NOTE_NAMES[((Math.round(m) % 12) + 12) % 12]}${Math.floor(Math.round(m) / 12) - 1}`;
