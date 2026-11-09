/**
 * A singer's voice as a few live settings: what a sung song leaves to the performer (the score
 * sets the notes, the vowels and the breath; these colour them), as a named style to pick, tweak
 * and keep. Every setting takes effect while a song plays; the body rebuilds the airway, so a
 * song restarts from where it was.
 *
 * Kept per browser: the styles saved by name, and the one each show was last sung with.
 */
import { useStore } from "./store.ts";
import { useSing } from "./singing.ts";
import { PRESETS, sameBody, type BodyMix } from "./body.ts";
import { DEFAULT_SOURCE } from "../wasm/engine.ts";

export interface VoiceStyle {
  body: BodyMix;
  /** lung pressure (cmH₂O): louder, harder singing */
  power: number;
  /** pressed phonation 0..1 */
  pressed: number;
  breathy: number;
  bright: number;
  rough: number;
  fry: number;
  /** the singer's ring: a narrowed epilarynx, the bright band near 3 kHz */
  ring: number;
  /** false-fold growl */
  growl: number;
  /** song vibrato depth (cents) and rate (Hz) */
  vibrato: number;
  rate: number;
  /** slow random pitch wander (cents): steadier (0) or looser */
  drift: number;
  /** semitones */
  transpose: number;
}

export const DEFAULT_STYLE: VoiceStyle = {
  body: PRESETS.male,
  power: DEFAULT_SOURCE.pressure,
  pressed: DEFAULT_SOURCE.tension,
  breathy: DEFAULT_SOURCE.breathiness,
  bright: DEFAULT_SOURCE.brightness,
  rough: DEFAULT_SOURCE.roughness,
  fry: DEFAULT_SOURCE.fry,
  ring: 0,
  growl: 0,
  vibrato: 35,
  rate: DEFAULT_SOURCE.vibratoRate,
  drift: DEFAULT_SOURCE.drift,
  transpose: 0,
};

/** ready-made characters (the body is left as it is) */
export const STYLE_PRESETS: { name: string; style: Partial<VoiceStyle> }[] = [
  { name: "Natural", style: {} },
  { name: "Soft", style: { power: 6, pressed: 0.3, breathy: 0.45, bright: 0.2, rough: 0.05, ring: 0.05, vibrato: 20, rate: 5.2, drift: 4 } },
  { name: "Pop", style: { power: 8.5, pressed: 0.45, breathy: 0.3, bright: 0.55, rough: 0.05, fry: 0.1, ring: 0.3, vibrato: 15, rate: 5.8, drift: 3 } },
  { name: "Rock", style: { power: 12, pressed: 0.75, breathy: 0.12, bright: 0.65, rough: 0.45, fry: 0.15, ring: 0.5, growl: 0.35, vibrato: 25, rate: 6.2, drift: 6 } },
  { name: "Opera", style: { power: 11, pressed: 0.55, breathy: 0.05, bright: 0.5, rough: 0.02, ring: 0.9, vibrato: 70, rate: 5.6, drift: 2 } },
  { name: "Crooner", style: { power: 7, pressed: 0.35, breathy: 0.3, bright: 0.15, rough: 0.08, fry: 0.25, ring: 0.15, vibrato: 40, rate: 5.0, drift: 5 } },
  { name: "Folk", style: { power: 8, pressed: 0.5, breathy: 0.2, bright: 0.4, rough: 0.15, ring: 0.35, vibrato: 10, rate: 6.0, drift: 8 } },
];

/** the voice as it is set now */
export function currentStyle(): VoiceStyle {
  const st = useStore.getState();
  const sg = useSing.getState();
  const s = st.source;
  return {
    body: st.body,
    power: s.pressure,
    pressed: s.tension,
    breathy: s.breathiness,
    bright: s.brightness,
    rough: s.roughness,
    fry: s.fry,
    ring: st.artic.epilarynx,
    growl: st.artic.ventricular,
    vibrato: sg.vibrato,
    rate: s.vibratoRate,
    drift: s.drift,
    transpose: sg.transpose,
  };
}

/** Set the voice to a style (only what differs; returns whether the body changed). */
export function applyStyle(v: Partial<VoiceStyle>): boolean {
  const st = useStore.getState();
  const sg = useSing.getState();
  const src: Record<string, number> = {};
  const put = (key: string, val: number | undefined) => {
    if (val !== undefined && Number.isFinite(val)) src[key] = val;
  };
  put("pressure", v.power);
  put("tension", v.pressed);
  put("breathiness", v.breathy);
  put("brightness", v.bright);
  put("roughness", v.rough);
  put("fry", v.fry);
  put("vibratoRate", v.rate);
  put("drift", v.drift);
  if (Object.keys(src).length) st.setSource(src);
  const art: Record<string, number> = {};
  if (v.ring !== undefined) art.epilarynx = v.ring;
  if (v.growl !== undefined) art.ventricular = v.growl;
  if (Object.keys(art).length) st.setArtic(art);
  if (v.vibrato !== undefined) sg.setVibrato(Math.round(v.vibrato));
  if (v.transpose !== undefined) sg.setTranspose(Math.round(v.transpose));
  if (v.body && !sameBody(v.body, st.body)) {
    st.setBody(v.body);
    return true;
  }
  return false;
}

/** a preset over the defaults, so nothing of the previous style lingers */
export const presetStyle = (p: Partial<VoiceStyle>, body: BodyMix): VoiceStyle => ({ ...DEFAULT_STYLE, ...p, body });

// ----------------------------------------------------------------------------- kept styles

const SAVED = "chimera.voiceStyles";
const showKey = (id: string) => `chimera.showVoice.${id}`;

function read<T>(key: string): T | null {
  try {
    const s = localStorage.getItem(key);
    return s ? (JSON.parse(s) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, v: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    // private window, storage full: the style just isn't kept
  }
}

export function savedStyles(): { name: string; style: VoiceStyle }[] {
  const l = read<{ name: string; style: VoiceStyle }[]>(SAVED);
  return Array.isArray(l) ? l.filter((x) => x && typeof x.name === "string" && x.style) : [];
}

export function saveStyle(name: string, style: VoiceStyle): void {
  write(SAVED, [...savedStyles().filter((s) => s.name !== name), { name, style }]);
}

export function deleteStyle(name: string): void {
  write(SAVED, savedStyles().filter((s) => s.name !== name));
}

export function showStyle(id: string): VoiceStyle | null {
  const s = read<VoiceStyle>(showKey(id));
  return s && typeof s === "object" ? { ...DEFAULT_STYLE, ...s } : null;
}

export function keepShowStyle(id: string, style: VoiceStyle): void {
  write(showKey(id), style);
}
