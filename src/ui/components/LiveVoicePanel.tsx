/**
 * The duet page's voice panel for a show sung live: who sings (a character to start from, or one
 * of your own, kept by name), their body, and the settings a sung song leaves to the singer, all
 * heard as they change. The show remembers the voice it was last sung with.
 */
import { useEffect, useState } from "react";
import { useStore } from "../store.ts";
import { useSing } from "../singing.ts";
import { bodyLabel, PRESETS } from "../body.ts";
import { BodyPad } from "./BodyPad.tsx";
import { EncoderPages, type EncoderPage } from "./Encoder.tsx";
import { Screen } from "./Screen.tsx";
import type { LiveShow } from "../liveShow.ts";
import { applyStyle, currentStyle, deleteStyle, keepShowStyle, presetStyle, savedStyles, saveStyle, STYLE_PRESETS, type VoiceStyle } from "../voiceStyle.ts";

const pct = (v: number) => ({ value: String(Math.round(v * 100)), unit: "%" });

export function LiveVoicePanel(props: { showId: string; live: LiveShow }) {
  const { live } = props;
  const body = useStore((s) => s.body);
  const src = useStore((s) => s.source);
  const ring = useStore((s) => s.artic.epilarynx);
  const growl = useStore((s) => s.artic.ventricular);
  const volume = useStore((s) => s.volume);
  const setVolume = useStore((s) => s.setVolume);
  const vibrato = useSing((s) => s.vibrato);
  const transpose = useSing((s) => s.transpose);
  const [band, setBand] = useState(0.8);
  const [saved, setSaved] = useState(savedStyles);
  const [picked, setPicked] = useState<string | null>(null);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  // keep the show's voice (after a pause in the changes)
  useEffect(() => {
    const id = setTimeout(() => keepShowStyle(props.showId, currentStyle()), 400);
    return () => clearTimeout(id);
  }, [props.showId, body, src, ring, growl, vibrato, transpose]);

  useEffect(() => {
    live.bandVolume = band;
  }, [live, band]);

  const set = (v: Partial<VoiceStyle>) => {
    setPicked(null);
    applyStyle(v);
  };
  const pick = (label: string, style: VoiceStyle) => {
    applyStyle(style);
    setPicked(label);
  };

  const pages: EncoderPage[] = [
    {
      name: "Song",
      encoders: [
        { label: "Vibrato", value: vibrato, min: 0, max: 100, onChange: (v) => set({ vibrato: v }), format: (v) => ({ value: String(Math.round(v)), unit: "cents" }) },
        { label: "Rate", value: src.vibratoRate, min: 3.5, max: 7.5, onChange: (v) => set({ rate: v }), format: (v) => ({ value: v.toFixed(1), unit: "Hz" }) },
        // sent half a second ahead of the voice, so a change is heard within that
        { label: "Transpose", value: transpose, min: -12, max: 12, onChange: (v) => set({ transpose: v }), format: (v) => ({ value: (v > 0 ? "+" : "") + Math.round(v), unit: "st" }) },
        { label: "Looseness", value: src.drift, min: 0, max: 30, onChange: (v) => set({ drift: v }), format: (v) => ({ value: String(Math.round(v)), unit: "cents" }) },
      ],
    },
    {
      name: "Tone",
      encoders: [
        { label: "Bright", value: src.brightness, min: 0, max: 1, onChange: (v) => set({ bright: v }), format: pct },
        { label: "Breathy", value: src.breathiness, min: 0, max: 1, onChange: (v) => set({ breathy: v }), format: pct },
        // the singer's ring narrows the tube just above the folds, adding the bright band near 3 kHz
        { label: "Ring", value: ring, min: 0, max: 1, onChange: (v) => set({ ring: v }), format: pct },
        { label: "Pressed", value: src.tension, min: 0, max: 1, onChange: (v) => set({ pressed: v }), format: pct },
      ],
    },
    {
      name: "Grit",
      encoders: [
        { label: "Rough", value: src.roughness, min: 0, max: 1, onChange: (v) => set({ rough: v }), format: pct },
        { label: "Fry", value: src.fry, min: 0, max: 1, onChange: (v) => set({ fry: v }), format: pct },
        { label: "Growl", value: growl, min: 0, max: 1, onChange: (v) => set({ growl: v }), format: pct },
        { label: "Power", value: src.pressure, min: 4, max: 16, onChange: (v) => set({ power: v }), format: (v) => ({ value: v.toFixed(1), unit: "cmH₂O" }) },
      ],
    },
    {
      name: "Mix",
      encoders: [
        { label: "Voice", value: volume, min: 0, max: 1, onChange: setVolume, format: pct },
        ...(live.hasBacking ? [{ label: "Band", value: band, min: 0, max: 1.2, onChange: setBand, format: pct }] : []),
      ],
    },
  ];

  return (
    <Screen className="duet-voice" focus title="Voice" sub={bodyLabel(body)} label="The live voice's settings">
      <div className="voice-panel">
        <div className="voice-styles" role="group" aria-label="Voice characters">
          {STYLE_PRESETS.map((p) => (
            <button key={p.name} type="button" className={`enc-tab${picked === p.name ? " on" : ""}`} aria-pressed={picked === p.name} onClick={() => pick(p.name, presetStyle(p.style, body))}>
              {p.name}
            </button>
          ))}
        </div>
        <div className="voice-styles mine" role="group" aria-label="Your voices">
          {saved.map((s) => (
            <span key={s.name} className={`voice-mine${picked === s.name ? " on" : ""}`}>
              <button type="button" className="enc-tab" aria-pressed={picked === s.name} onClick={() => pick(s.name, s.style)}>
                {s.name}
              </button>
              <button
                type="button"
                className="enc-tab voice-del"
                aria-label={`Forget the voice ${s.name}`}
                title="Forget this voice"
                onClick={() => {
                  deleteStyle(s.name);
                  setSaved(savedStyles());
                }}
              >
                ×
              </button>
            </span>
          ))}
          {naming ? (
            <form
              className="voice-save"
              onSubmit={(e) => {
                e.preventDefault();
                const n = name.trim().slice(0, 24);
                if (!n) return;
                saveStyle(n, currentStyle());
                setSaved(savedStyles());
                setPicked(n);
                setNaming(false);
                setName("");
              }}
            >
              <input autoFocus aria-label="Name for this voice" placeholder="Name" value={name} maxLength={24} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setNaming(false)} />
              <button type="submit" className="enc-tab on">
                Save
              </button>
            </form>
          ) : (
            <button type="button" className="enc-tab" onClick={() => setNaming(true)} title="Keep these settings as one of your voices">
              + Save voice
            </button>
          )}
        </div>
        <div className="voice-body">
          <BodyPad />
          <div className="voice-body-presets" role="group" aria-label="Body">
            {(["male", "female", "child", "neanderthal"] as const).map((b) => (
              <button key={b} type="button" className="enc-tab" onClick={() => set({ body: PRESETS[b] })}>
                {b === "male" ? "Male" : b === "female" ? "Female" : b === "child" ? "Child" : "Neanderthal"}
              </button>
            ))}
          </div>
        </div>
        <EncoderPages label="Voice" pages={pages} />
        {live.error && <p className="voice-error">{live.error}</p>}
      </div>
    </Screen>
  );
}
