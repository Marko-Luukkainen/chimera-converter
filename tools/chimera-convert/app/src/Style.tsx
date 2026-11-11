import { useState } from "react";
import { api, type Info, type RapSettings, type Session, type SpeechSettings, type Style } from "./api.ts";

/** the server's defaults (rap.Opts), used until /api/info has answered */
export const RAP_DEFAULTS: RapSettings = { rest: 0.15, window: 0.08, min_rise: 4, nucleus: 0.7, keep_cents: true };

export const SPEECH_DEFAULTS: SpeechSettings = { rest: 0.25, window: 0.08, min_rise: 4, nucleus: 0.7, pitch: "voice", expression: 1, dynamics: 1 };

export const STYLE_NAMES: Record<Style, string> = { sing: "Singing", rap: "Rap", speech: "Speech" };

/** what each style does, in a line */
export const STYLE_HELP: Record<Style, string> = {
  sing: "Notes first, syllables on them: held notes, melismas and vibrato.",
  rap: "Words first, one note per syllable at the pitch inside it: fast flows and speech-like pitch. Keep the ad-libs that are on the recording in the lyrics.",
  speech:
    "Said, not sung: Chimera's speech voice with the recording's timing, intonation and stresses (its pitch and loudness contours). Write the words exactly as they are said.",
};

/** The speech style's settings: the intonation's range, how lively it is, how strong the
 * stresses are, and what makes a pause; the timing settings are the rap style's. */
export function SpeechSettingsFields({ value, onChange, defaults }: { value: SpeechSettings; onChange: (v: SpeechSettings) => void; defaults?: SpeechSettings }) {
  const d = defaults ?? SPEECH_DEFAULTS;
  const set = (k: keyof SpeechSettings, v: number | string) => onChange({ ...value, [k]: v });
  const changed = (Object.keys(d) as (keyof SpeechSettings)[]).some((k) => value[k] !== d[k]);
  return (
    <div className="rap-settings">
      <label title="The intonation at the chosen voice's own range (a male voice says a woman's sentence an octave down), or at the speaker's own pitch.">
        <span>Pitch</span>
        <span className="seg small">
          <button type="button" className={value.pitch === "voice" ? "on" : ""} onClick={() => set("pitch", "voice")}>
            Voice's range
          </button>
          <button type="button" className={value.pitch === "speaker" ? "on" : ""} onClick={() => set("pitch", "speaker")}>
            Speaker's own
          </button>
        </span>
      </label>
      <label title="The intonation's rises and falls, scaled: 100 % as spoken, less is flatter, more is livelier.">
        <span>Intonation</span>
        <input type="number" min={0} max={200} step={10} value={Math.round(value.expression * 100)} onChange={(e) => set("expression", Math.max(0, Number(e.target.value)) / 100)} />
        <i>%</i>
      </label>
      <label title="How much louder stressed and emphasised syllables are than the rest: 100 % as spoken, 0 even.">
        <span>Stresses</span>
        <input type="number" min={0} max={200} step={10} value={Math.round(value.dynamics * 100)} onChange={(e) => set("dynamics", Math.max(0, Number(e.target.value)) / 100)} />
        <i>%</i>
      </label>
      <label title="A silence at least this long between syllables is a pause: Chimera breathes there. Shorter gaps are held over.">
        <span>Pause after a silence of</span>
        <input type="number" min={0.05} max={1.5} step={0.05} value={value.rest} onChange={(e) => set("rest", Number(e.target.value) || d.rest)} />
        <i>s</i>
      </label>
      <label title="How far a syllable's start may move from the alignment model's time onto its vowel's rise. 0 keeps the model's times.">
        <span>Move onsets onto vowels within</span>
        <input type="number" min={0} max={200} step={10} value={Math.round(value.window * 1000)} onChange={(e) => set("window", Math.max(0, Number(e.target.value)) / 1000)} />
        <i>ms</i>
      </label>
      <label title="How steep a rise of the vowel band must be to count as a vowel starting.">
        <span>A vowel starts at a rise of</span>
        <input type="number" min={1} max={15} step={0.5} value={value.min_rise} onChange={(e) => set("min_rise", Number(e.target.value) || d.min_rise)} />
        <i>dB / 20 ms</i>
      </label>
      {changed && (
        <button type="button" className="link" onClick={() => onChange({ ...d })}>
          Defaults
        </button>
      )}
    </div>
  );
}

/** The rap style's settings: what makes a rest, how far a syllable may move onto its vowel, what
 * counts as a vowel starting, which part of a syllable gives its pitch, and notes to the cent. */
export function RapSettingsFields({ value, onChange, defaults }: { value: RapSettings; onChange: (v: RapSettings) => void; defaults?: RapSettings }) {
  const d = defaults ?? RAP_DEFAULTS;
  const set = (k: keyof RapSettings, v: number | boolean) => onChange({ ...value, [k]: v });
  const changed = (Object.keys(d) as (keyof RapSettings)[]).some((k) => value[k] !== d[k]);
  return (
    <div className="rap-settings">
      <label title="A silence at least this long before the next syllable becomes a rest (a breath); shorter gaps are consonants and the syllable is held over them.">
        <span>Rest after a silence of</span>
        <input type="number" min={0.05} max={1} step={0.05} value={value.rest} onChange={(e) => set("rest", Number(e.target.value) || d.rest)} />
        <i>s</i>
      </label>
      <label title="How far a syllable's start may move from the alignment model's time onto its vowel's rise. 0 keeps the model's times.">
        <span>Move onsets onto vowels within</span>
        <input
          type="number"
          min={0}
          max={200}
          step={10}
          value={Math.round(value.window * 1000)}
          onChange={(e) => set("window", Math.max(0, Number(e.target.value)) / 1000)}
        />
        <i>ms</i>
      </label>
      <label title="How steep a rise of the vowel band (150–1200 Hz) must be to count as a vowel starting. Lower finds more vowels in legato flows, higher ignores noise.">
        <span>A vowel starts at a rise of</span>
        <input type="number" min={1} max={15} step={0.5} value={value.min_rise} onChange={(e) => set("min_rise", Number(e.target.value) || d.min_rise)} />
        <i>dB / 20 ms</i>
      </label>
      <label title="Each syllable's pitch is the median of this part of it, from its start: the vowel, before the consonants that close it.">
        <span>Pitch from the first</span>
        <input
          type="number"
          min={20}
          max={100}
          step={5}
          value={Math.round(value.nucleus * 100)}
          onChange={(e) => set("nucleus", (Number(e.target.value) || d.nucleus * 100) / 100)}
        />
        <i>% of each syllable</i>
      </label>
      <label className="check" title="Keep each syllable's pitch to the cent (speech-like). Off rounds every note to the nearest semitone.">
        <input type="checkbox" checked={value.keep_cents} onChange={(e) => set("keep_cents", e.target.checked)} />
        Keep the pitch to the cent
      </label>
      {changed && (
        <button type="button" className="link" onClick={() => onChange({ ...d })}>
          Defaults
        </button>
      )}
    </div>
  );
}

/** How the voice is separated from the backing (New song only: it is part of the analysis). */
export function SeparationFields({
  info,
  separator,
  leadOnly,
  onSeparator,
  onLeadOnly,
}: {
  info: Info | null;
  separator: string;
  leadOnly: boolean;
  onSeparator: (v: string) => void;
  onLeadOnly: (v: boolean) => void;
}) {
  const roformer = info?.separators?.roformer ?? false;
  return (
    <div className="separation">
      <label className="check">
        Separator
        <select value={separator} onChange={(e) => onSeparator(e.target.value)} name="separator">
          <option value="htdemucs">Demucs (fast, about a minute)</option>
          <option value="htdemucs_ft">Demucs fine-tuned (cleaner, about twice as slow)</option>
          <option value="roformer" disabled={!roformer}>
            RoFormer (cleanest, about 10 minutes){roformer ? "" : " — run scripts\\install_separator.bat"}
          </option>
        </select>
      </label>
      <label className="check" title={roformer ? "" : "Needs scripts\\install_separator.bat"}>
        <input type="checkbox" checked={leadOnly} disabled={!roformer} onChange={(e) => onLeadOnly(e.target.checked)} />
        Lead voice only (drops backing vocals, doubles and ad-libs; can drop a hook sung by other voices — you are warned where)
      </label>
    </div>
  );
}

/** The song's style in the editor's header: change it, or the rap settings, and the notes are made
 * again from the kept analysis (seconds; edits are lost). */
export function StyleChip({ s, info, onQueued }: { s: Session; info: Info | null; onQueued: (soon: Partial<Session>) => void }) {
  const style: Style = s.options.style ?? "sing";
  const [open, setOpen] = useState(false);
  const [want, setWant] = useState<Style>(style);
  const [rap, setRap] = useState<RapSettings>({ ...(info?.rap_defaults ?? RAP_DEFAULTS), ...(s.options.rap ?? {}) });
  const [speech, setSpeech] = useState<SpeechSettings>({ ...(info?.speech_defaults ?? SPEECH_DEFAULTS), ...(s.options.speech ?? {}) });
  const [err, setErr] = useState<string | null>(null);
  const busy = s.status === "queued" || s.status === "running";
  const noAlign = s.options.align !== "mms";
  const apply = async () => {
    if (!confirm(`Convert it again as ${STYLE_NAMES[want].toLowerCase()}? Your edits to the notes are lost.`)) return;
    setErr(null);
    try {
      await api.setStyle(s.id, want, want === "rap" ? rap : undefined, want === "speech" ? speech : undefined);
      setOpen(false);
      onQueued({
        status: "queued",
        stage: "Queued",
        progress: 0,
        options: { ...s.options, style: want, rap: want === "rap" ? rap : s.options.rap, speech: want === "speech" ? speech : s.options.speech },
      });
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="style-chip">
      <span>Style</span>
      <b>{STYLE_NAMES[style]}</b>
      {style === "rap" && s.options.rap && (
        <span className="dim">
          rest {s.options.rap.rest} s · onsets ±{Math.round(s.options.rap.window * 1000)} ms · pitch {Math.round(s.options.rap.nucleus * 100)} %
          {s.options.rap.keep_cents ? " · cents" : ""}
        </span>
      )}
      {style === "speech" && s.options.speech && (
        <span className="dim">
          {s.options.speech.pitch === "voice" ? "voice's range" : "speaker's pitch"} · intonation {Math.round(s.options.speech.expression * 100)} % · stresses{" "}
          {Math.round(s.options.speech.dynamics * 100)} % · pause {s.options.speech.rest} s
        </span>
      )}
      {s.options.separator && (
        <span className="dim">
          · {s.options.separator}
          {s.options.lead_only ? ", lead voice" : ""}
        </span>
      )}
      <button onClick={() => setOpen((v) => !v)} disabled={busy}>
        {open ? "Close" : "Change…"}
      </button>
      {open && (
        <div className="panel style-panel">
          <div className="seg">
            {(["sing", "rap", "speech"] as Style[]).map((k) => (
              <button key={k} className={want === k ? "on" : ""} onClick={() => setWant(k)} disabled={k !== "sing" && noAlign} type="button">
                {STYLE_NAMES[k]}
              </button>
            ))}
          </div>
          <div className="dim">{STYLE_HELP[want]}</div>
          {noAlign && <div className="warn">Rap and speech need the automatic lyrics alignment: add the song again with it.</div>}
          {want === "rap" && <RapSettingsFields value={rap} onChange={setRap} defaults={info?.rap_defaults} />}
          {want === "speech" && <SpeechSettingsFields value={speech} onChange={setSpeech} defaults={info?.speech_defaults} />}
          {err && <div className="error">{err}</div>}
          <div className="actions">
            <button className="primary" onClick={apply}>
              Convert again
            </button>
            <span className="dim">Uses the analysis already made: takes seconds. Your edits to the notes are lost.</span>
          </div>
        </div>
      )}
    </div>
  );
}
