import { useEffect, useRef, useState } from "react";
import { api, ApiError, LANG_NAMES, type Detection, type Info, type Lang, type RapSettings, type Style } from "./api.ts";
import { RAP_DEFAULTS, RapSettingsFields, SeparationFields } from "./Style.tsx";

type LangChoice = "auto" | Lang;

/** Upload a recording and its lyrics. The language is read from the lyrics as they're typed;
 * when it can't be told, the user picks it before converting. */
export function NewSong(props: { onCreated: (id: string) => void; info?: Info | null }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [lang, setLang] = useState<LangChoice>("auto");
  const [separate, setSeparate] = useState(true);
  const [review, setReview] = useState(true);
  const [align, setAlign] = useState("mms");
  const [style, setStyle] = useState<Style>("sing");
  const [rap, setRap] = useState<RapSettings | null>(null);
  const rapValue = rap ?? props.info?.rap_defaults ?? RAP_DEFAULTS;
  const [separator, setSeparator] = useState("htdemucs");
  const [leadOnly, setLeadOnly] = useState(false);
  const [det, setDet] = useState<Detection | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!lyrics.trim()) return setDet(null);
    const h = setTimeout(() => api.detect(lyrics).then(setDet).catch(() => setDet(null)), 350);
    return () => clearTimeout(h);
  }, [lyrics]);

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  };

  const needLang = lang === "auto" && (!det || det.lang === null);
  const ready = !!file && lyrics.trim().length > 0 && !needLang && !busy;

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    const form = new FormData();
    form.append("audio", file);
    form.append("lyrics", lyrics);
    form.append("lang", lang);
    form.append("separate", String(separate));
    form.append("review", String(review));
    form.append("title", title);
    form.append("align", align);
    form.append("style", style);
    if (style === "rap") form.append("rap", JSON.stringify(rapValue));
    if (separate) {
      form.append("separator", separator);
      form.append("lead_only", String(leadOnly));
    }
    try {
      setSent(0);
      const s = await api.upload(form, setSent);
      props.onCreated(s.id);
    } catch (e) {
      if (e instanceof ApiError && e.body?.need === "lang") {
        setDet(e.body.detection);
        setLang("auto");
      }
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel new-song">
      <h2>New song</h2>
      <div
        className={`drop ${drag ? "over" : ""} ${file ? "has" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          pick(e.dataTransfer.files[0]);
        }}
      >
        <input ref={input} type="file" accept="audio/*,.mp3,.wav,.flac,.ogg,.m4a" hidden onChange={(e) => pick(e.target.files?.[0])} />
        {file ? (
          <>
            <b>{file.name}</b> <span className="dim">{(file.size / 1e6).toFixed(1)} MB · click to change</span>
          </>
        ) : (
          <span>Drop a recording here (wav, mp3, flac …) or click</span>
        )}
      </div>

      <label className="field">
        <span>Title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Song title" />
      </label>

      <label className="field">
        <span>Lyrics</span>
        <textarea
          value={lyrics}
          onChange={(e) => setLyrics(e.target.value)}
          rows={9}
          placeholder={"Write the lyrics as they are sung.\nLine breaks and commas are breaths."}
        />
      </label>

      <fieldset className="field lang">
        <span>Language</span>
        <div className="seg">
          {(["auto", "fi", "en"] as LangChoice[]).map((l) => (
            <button key={l} className={lang === l ? "on" : ""} onClick={() => setLang(l)} type="button">
              {l === "auto" ? "Detect" : l === "fi" ? "Finnish" : "English"}
            </button>
          ))}
        </div>
        <LangStatus det={det} choice={lang} />
      </fieldset>

      <label className="check">
        <input type="checkbox" checked={separate} onChange={(e) => setSeparate(e.target.checked)} />
        Separate the voice from the backing (leave on for finished songs; off only for a cappella)
      </label>
      {separate && (
        <SeparationFields info={props.info ?? null} separator={separator} leadOnly={leadOnly} onSeparator={setSeparator} onLeadOnly={setLeadOnly} />
      )}

      <label className="check">
        <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
        Let me check what counts as singing before the notes are made
      </label>

      <fieldset className="field style-field">
        <span>Style</span>
        <div className="seg">
          {(["sing", "rap"] as Style[]).map((k) => (
            <button
              key={k}
              type="button"
              className={style === k ? "on" : ""}
              onClick={() => {
                setStyle(k);
                if (k === "rap") setAlign("mms");
              }}
            >
              {k === "sing" ? "Singing" : "Rap"}
            </button>
          ))}
        </div>
        <div className="dim">
          {style === "sing"
            ? "Notes first, syllables on them: held notes, melismas and vibrato."
            : "Words first, one note per syllable at the pitch inside it: fast flows and speech-like pitch. Keep the ad-libs that are on the recording in the lyrics."}
        </div>
        {style === "rap" && <RapSettingsFields value={rapValue} onChange={setRap} defaults={props.info?.rap_defaults} />}
      </fieldset>

      <label className="check">
        Lyrics alignment
        <select value={align} onChange={(e) => setAlign(e.target.value)} name="align" disabled={style === "rap"}>
          <option value="mms">Automatic (speech alignment model)</option>
          <option value="none">In order (no model, needs more fixing)</option>
        </select>
      </label>

      {err && <div className="error">{err}</div>}
      <div className="actions">
        <button className="primary big" disabled={!ready} onClick={submit}>
          {busy ? `Uploading ${Math.round(sent * 100)} %` : "Convert"}
        </button>
        {busy && (
          <div className="bar upload">
            <div style={{ width: `${Math.round(sent * 100)}%` }} />
          </div>
        )}
      </div>
      {!busy && (
        <ul className="checklist" aria-label="Before converting">
          <Check ok={!!file} done={file ? `Recording: ${file.name}` : ""} todo="Add a recording (drop it above or click the box)" />
          <Check ok={lyrics.trim().length > 0} done={`Lyrics: ${lyrics.trim().split(/\s+/).filter(Boolean).length} words`} todo="Type or paste the lyrics" />
          <Check
            ok={lyrics.trim().length > 0 && !needLang}
            done={`Language: ${LANG_NAMES[lang === "auto" ? det?.lang ?? "" : lang] ?? ""}${lang === "auto" ? " (detected)" : ""}`}
            todo={lyrics.trim() ? "Choose the language (Finnish or English): it can't be told from the lyrics" : "Language: detected from the lyrics once you type them"}
          />
          {ready && <li className="go">Ready: press Convert. The song then opens with its progress.</li>}
        </ul>
      )}
    </div>
  );
}

function LangStatus({ det, choice }: { det: Detection | null; choice: LangChoice }) {
  if (!det) return <div className="lang-status dim">The language is detected from the lyrics.</div>;
  const pct = Math.round(det.confidence * 100);
  if (choice === "auto") {
    return <div className={`lang-status ${det.lang ? "ok" : "warn"}`}>{det.lang ? `${det.reason} (${pct} %)` : det.reason}</div>;
  }
  if (det.lang && det.lang !== choice) {
    return (
      <div className="lang-status warn">
        The lyrics look like {LANG_NAMES[det.lang]}, but they will be sung as you chose: {LANG_NAMES[choice]}.
      </div>
    );
  }
  return <div className="lang-status ok">Sung in {LANG_NAMES[choice]}.</div>;
}

function Check({ ok, done, todo }: { ok: boolean; done: string; todo: string }) {
  return <li className={ok ? "ok" : "todo"}>{ok ? `✓ ${done}` : `○ ${todo}`}</li>;
}
