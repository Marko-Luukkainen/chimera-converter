/**
 * The continuous body (see `BodyMix` in the engine): the page's twin of its weights, so the UI can
 * blend the few per-body things it keeps itself (default pitch, vowel chart, keyboard range).
 */
import type { BodyMix } from "../wasm/types.ts";
import type { BodyName } from "../worklet/protocol.ts";

export type { BodyMix };

/** the bodies calibrated against recordings; the Neanderthal borrows the adult male's tables */
export type CalibratedBody = Exclude<BodyName, "neanderthal">;

export const PRESETS: Record<BodyName, BodyMix> = {
  male: { female: 0, child: 0 },
  female: { female: 1, child: 0 },
  child: { female: 0, child: 1 },
  neanderthal: { female: 0, child: 0, neanderthal: 1 },
};

export const PRESET_LABEL: Record<BodyName, string> = { male: "Adult male", female: "Adult female", child: "Child", neanderthal: "Neanderthal" };

const clamp01 = (x: number) => (Number.isFinite(x) ? Math.min(1, Math.max(0, x)) : 0);

/** Weights of male, female, child and Neanderthal (as the engine computes them; they sum to 1). */
export function bodyWeights(b: BodyMix): [BodyName, number][] {
  const f = clamp01(b.female), c = clamp01(b.child), n = clamp01(b.neanderthal ?? 0);
  return [
    ["male", (1 - n) * (1 - c) * (1 - f)],
    ["female", (1 - n) * (1 - c) * f],
    ["child", (1 - n) * c],
    ["neanderthal", n],
  ];
}

/** The preset this body is exactly, or null. */
export function presetOf(b: BodyMix): BodyName | null {
  return bodyWeights(b).find(([, w]) => w === 1)?.[0] ?? null;
}

/** The preset with the largest weight (for things that stay per preset, like the keyboard's octave). */
export function nearestBody(b: BodyMix): BodyName {
  return bodyWeights(b).reduce((best, x) => (x[1] > best[1] ? x : best))[0];
}

/** The calibrated tables a body name reads (the engine's `BodyName::cal_name`). */
export const calibrated = (n: BodyName): CalibratedBody => (n === "neanderthal" ? "male" : n);

/** How much of the Neanderthal this body is (0 for a modern human). */
export const neanderthalShare = (b: BodyMix) => clamp01(b.neanderthal ?? 0);

export function sameBody(a: BodyMix | null | undefined, b: BodyMix | null | undefined): boolean {
  return !!a && !!b && a.female === b.female && a.child === b.child && (a.neanderthal ?? 0) === (b.neanderthal ?? 0);
}

export const bodyKey = (b: BodyMix) => `${b.female},${b.child},${b.neanderthal ?? 0}`;

/**
 * A per-preset quantity blended by the body's weights (geometrically: pitches, frequencies). The
 * Neanderthal's value is the adult male's unless given.
 */
export function blendLog(b: BodyMix, of: Record<CalibratedBody, number> & { neanderthal?: number }): number {
  const at = (n: BodyName) => (n === "neanderthal" ? (of.neanderthal ?? of.male) : of[n]);
  const p = presetOf(b);
  if (p) return at(p);
  return Math.exp(bodyWeights(b).reduce((s, [n, w]) => (w > 0 ? s + w * Math.log(at(n)) : s), 0));
}

/** Default pitch: the presets' (as the engine's `default_f0`), blended geometrically in between. */
export const defaultF0 = (b: BodyMix) => blendLog(b, { male: 110, female: 205, child: 260, neanderthal: 100 });

/** "Adult female", or the blend's shares: "Male 40 · Female 30 · Child 30 %". */
export function bodyLabel(b: BodyMix): string {
  const p = presetOf(b);
  if (p) return PRESET_LABEL[p];
  const parts = bodyWeights(b)
    .filter(([, w]) => w > 0.005)
    .map(([n, w]) => `${n[0].toUpperCase()}${n.slice(1)} ${Math.round(w * 100)}`);
  return `${parts.join(" · ")} %`;
}
