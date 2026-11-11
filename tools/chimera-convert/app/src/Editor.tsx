import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, LANG_NAMES, type Info, type Lang, type RenderJob, type Session } from "./api.ts";
import { innerMelismas, mergePrev, noteName, setPitch, shiftSyllable, split, valid, type Note } from "./edit.ts";
import { Roll } from "./Roll.tsx";
import { SingingCheck } from "./Singing.tsx";
import { StyleChip } from "./Style.tsx";

type Source = "original" | "vocals" | "chimera";
const BODIES: [string, string][] = [["female", "Female"], ["male", "Male"], ["child", "Child"]];

/** One song: conversion progress, then the editor. */
export function Editor(props: { id: string; info: Info | null; onChanged: () => void; onStatus?: (s: Session) => void }) {
  const [s, setS] = useState<Session | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // poll while the conversion runs
  useEffect(() => {
    let stop = false;
    let timer = 0;
    const tick = async () => {
      try {
        const x = await api.session(props.id);
        if (stop) return;
        setS(x);
        props.onStatus?.(x);
        setErr(null);
        if (x.status === "queued" || x.status === "running") timer = window.setTimeout(tick, 800);
        else props.onChanged();
      } catch (e) {
        if (!stop) setErr((e as Error).message);
      }
    };
    setS(null);
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [props.id]);

  // follow the song again after asking the server for something (new notes, a new language)
  const follow = (soon: Partial<Session>) => {
    if (!s) return;
    setS({ ...s, ...soon });
    const poll = async () => {
      const x = await api.session(s.id);
      setS(x);
      props.onStatus?.(x);
      if (x.status === "queued" || x.status === "running") setTimeout(poll, 800);
      else props.onChanged();
    };
    setTimeout(poll, 300);
  };

  const relang = async (lang: Lang) => {
    if (!s || lang === s.lang) return;
    if (!confirm(`Sing the song in ${LANG_NAMES[lang]}? The syllables change, so the notes are placed again and your edits are lost.`)) return;
    await api.setLang(s.id, lang);
    follow({ status: "queued", stage: "Queued", progress: 0, lang });
  };
  const toReview = async () => {
    if (!s) return;
    const r = await api.review(s.id);
    follow({ status: r.status, stage: r.stage, progress: r.progress });
  };

  if (err) return <div className="panel error">{err}</div>;
  if (!s) return <div className="panel dim">Loading …</div>;
  return (
    <div className="editor-wrap">
      <header className="song-head">
        <h2>{s.title}</h2>
        <LangChip s={s} onChange={relang} />
        <StyleChip key={`${s.id}-${s.options.style ?? "sing"}`} s={s} info={props.info} onQueued={follow} />
      </header>
      {(s.status === "queued" || s.status === "running") && <Progress s={s} />}
      {s.status === "error" && (
        <div className="panel error">
          Conversion failed: {s.error}{" "}
          <button
            onClick={async () => {
              await api.setLang(s.id, s.lang);
              setS({ ...s, status: "queued", stage: "Queued", progress: 0, error: null });
              const poll = async () => {
                const x = await api.session(s.id);
                setS(x);
                props.onStatus?.(x);
                if (x.status === "queued" || x.status === "running") setTimeout(poll, 800);
                else props.onChanged();
              };
              setTimeout(poll, 500);
            }}
          >
            Try again
          </button>
        </div>
      )}
      {s.status === "review" && <SingingCheck key={s.id} s={s} onQueued={() => follow({ status: "queued", stage: "Queued", progress: 0 })} />}
      {s.status === "done" && s.notes && (
        <EditorBody key={`${s.id}-${s.lang}-${s.created}-${s.options.style ?? "sing"}-${JSON.stringify(s.options.rap ?? {})}`} s={s} info={props.info} onReview={toReview} />
      )}
    </div>
  );
}

function LangChip({ s, onChange }: { s: Session; onChange: (l: Lang) => void }) {
  const d = s.detection;
  const how =
    s.lang_requested === "auto"
      ? `detected from the lyrics (${Math.round(d.confidence * 100)} %)`
      : d.lang && d.lang !== s.lang
        ? `chosen; the lyrics look like ${LANG_NAMES[d.lang]}`
        : "chosen";
  return (
    <div className="lang-chip">
      <span>Language</span>
      <select value={s.lang} onChange={(e) => onChange(e.target.value as Lang)} disabled={s.status === "running" || s.status === "queued"}>
        <option value="fi">Finnish</option>
        <option value="en">English</option>
      </select>
      <span className="dim">{how}</span>
    </div>
  );
}

/** the server's stages, in order (server.py STAGES) */
const STEPS: [string, string][] = [
  ["Queued", "Waiting for its turn"],
  ["Preparing", "Reading the lyrics"],
  ["Separating the voice", "Separating the voice from the backing"],
  ["Loading the audio", "Loading the audio"],
  ["Tracking the pitch", "Tracking the sung pitch"],
  ["Aligning the lyrics", "Aligning the lyrics with the singing"],
  ["Making the notes", "Making the notes"],
];

function Progress({ s }: { s: Session }) {
  const [now, setNow] = useState(Date.now());
  const since = useRef(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  const steps = STEPS.filter(([k]) => (k === "Separating the voice" ? s.options.separate : k === "Loading the audio" ? !s.options.separate : true));
  const at = Math.max(0, steps.findIndex(([k]) => k === s.stage));
  const secs = Math.round((now - since.current) / 1000);
  return (
    <div className="panel progress">
      <div className="progress-head">
        <i className="pulse" />
        <b>Processing</b>
        <span>{Math.round(s.progress * 100)} %</span>
        <span className="dim">
          {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, "0")}
        </span>
      </div>
      <div className="bar live">
        <div style={{ width: `${Math.max(3, Math.round(s.progress * 100))}%` }} />
      </div>
      <ol className="steps">
        {steps.map(([k, label], i) => (
          <li key={k} className={i < at ? "done" : i === at ? "now" : "todo"}>
            {i < at ? "✓" : i === at ? "▸" : "○"} {label}
          </li>
        ))}
      </ol>
      <span className="dim">
        The editor opens here when the notes are ready. The first run downloads the models (about 1.3 GB), so it takes longer; a 3-minute
        song usually takes under a minute after that{s.options.separate ? ", plus a minute or two to separate the voice" : ""}.
      </span>
    </div>
  );
}

function EditorBody({ s, info, onReview }: { s: Session; info: Info | null; onReview: () => void }) {
  const [notes, setNotes] = useState<Note[]>(s.notes!);
  const [history, setHistory] = useState<{ past: Note[][]; future: Note[][] }>({ past: [], future: [] });
  const [sel, setSel] = useState<number | null>(null);
  const [body, setBody] = useState(s.body ?? "female");
  const [transpose, setTranspose] = useState(s.transpose ?? 0);
  const [vibrato, setVibrato] = useState(s.vibrato ?? 35);
  const [melody, setMelody] = useState(s.melody);
  const [warnings, setWarnings] = useState<string[]>(s.warnings ?? []);
  const [render, setRender] = useState(s.render ?? null);
  const [renderUrl, setRenderUrl] = useState<string | null>(s.render ? api.file(s.id, `render.wav?t=${Math.round(s.render.time)}`) : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string; link?: string } | null>(null);
  const [source, setSource] = useState<Source>(s.files.vocals ? "vocals" : "original");
  const [playing, setPlaying] = useState(false);
  const [showOpen, setShowOpen] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const playhead = useRef(0);
  const saveTimer = useRef(0);

  const nSyl = s.syllables!.length;
  /** the speech style: said by Chimera's speech planner (no vibrato, no live or duet pages) */
  const spoken = s.melody?.kind === "spoken";
  const melodyOnly = "Chimera's live and duet pages sing melodies: speech is heard here (Speak with Chimera) and in the downloaded file";
  const sylsPerWord = useMemo(() => s.lyrics!.words.map((w) => w.syls.length), [s]);
  // only English folds a melisma inside a word (Finnish words are written in parts around it)
  const flagged = useMemo(() => (s.lang === "en" ? innerMelismas(notes, s.syl_word!, sylsPerWord) : new Set<number>()), [notes, s, sylsPerWord]);
  const [doubtSyl, setDoubtSyl] = useState<Set<number>>(() => new Set(s.doubtful ?? []));
  const doubtful = useMemo(() => new Set(notes.flatMap((n, i) => (n.syl !== null && doubtSyl.has(n.syl) ? [i] : []))), [notes, doubtSyl]);
  const [focus, setFocus] = useState<{ t: number } | null>(null);
  const nextDoubt = () => {
    const list = [...doubtful].sort((a, b) => a - b);
    if (!list.length) return;
    const i = list.find((j) => sel === null || j > sel) ?? list[0];
    setSel(i);
    setFocus({ t: notes[i].start });
  };
  const offset = melody?.offset ?? 0;
  const stale = !render || JSON.stringify(render.melody) !== JSON.stringify(melody);

  // ---- saving
  const save = useCallback(
    (ns: Note[], b = body, tr = transpose, vib = vibrato) => {
      clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(async () => {
        try {
          const r = await api.saveNotes(s.id, { notes: ns, body: b, transpose: tr, vibrato: vib });
          setMelody(r.melody);
          setWarnings(r.warnings);
          // the server folds what Chimera can't sing; show what it kept
          if (JSON.stringify(r.notes) !== JSON.stringify(ns)) setNotes(r.notes);
        } catch (e) {
          setMsg({ kind: "error", text: `Saving failed: ${(e as Error).message}` });
        }
      }, 500);
    },
    [s.id, body, transpose, vibrato],
  );

  const commit = (ns: Note[] | null, from: Note[] = notes) => {
    if (!ns || !valid(ns, nSyl)) return false;
    setHistory((h) => ({ past: [...h.past.slice(-100), from], future: [] }));
    setNotes(ns);
    save(ns);
    return true;
  };
  const dragStart = useRef<Note[] | null>(null);
  const onRollChange = (ns: Note[], done: boolean) => {
    if (!done) {
      if (!dragStart.current) dragStart.current = notes;
      setNotes(ns);
      return;
    }
    const from = dragStart.current ?? notes;
    dragStart.current = null;
    if (!commit(ns, from)) setNotes(from);
  };
  const undo = () =>
    setHistory((h) => {
      if (!h.past.length) return h;
      const prev = h.past[h.past.length - 1];
      setNotes(prev);
      save(prev);
      return { past: h.past.slice(0, -1), future: [notes, ...h.future] };
    });
  const redo = () =>
    setHistory((h) => {
      if (!h.future.length) return h;
      const next = h.future[0];
      setNotes(next);
      save(next);
      return { past: [...h.past, notes], future: h.future.slice(1) };
    });

  // ---- operations on the selected note
  const op = {
    pitch: (d: number) => sel !== null && commit(setPitch(notes, sel, Math.round(notes[sel].midi) + d)),
    split: () => {
      if (sel === null) return;
      const n = notes[sel];
      const t = playhead.current > n.start + 0.05 && playhead.current < n.end - 0.05 ? playhead.current : (n.start + n.end) / 2;
      commit(split(notes, sel, t));
    },
    merge: () => {
      if (sel === null) return;
      if (commit(mergePrev(notes, sel))) setSel(sel - 1);
    },
    shift: (dir: -1 | 1) => {
      if (sel === null) return;
      if (commit(shiftSyllable(notes, sel, dir))) setSel(sel + dir);
    },
  };
  const can = {
    merge: sel !== null && !!mergePrev(notes, sel),
    split: sel !== null && notes[sel].end - notes[sel].start >= 0.1,
    left: sel !== null && !!shiftSyllable(notes, sel, -1),
    right: sel !== null && !!shiftSyllable(notes, sel, 1),
  };

  // ---- playback
  const srcUrl = source === "chimera" ? renderUrl : api.file(s.id, source === "vocals" ? "vocals.wav" : "original");
  const shift = source === "chimera" ? offset : 0;
  useEffect(() => {
    const a = audio.current;
    if (!a) return;
    let raf = 0;
    const loop = () => {
      playhead.current = Math.max(0, a.currentTime - shift);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [shift, srcUrl]);
  useEffect(() => {
    const a = audio.current;
    if (!a || !srcUrl) return;
    const t = playhead.current;
    const was = !a.paused;
    a.src = srcUrl;
    a.currentTime = t + shift;
    if (was) a.play().catch(() => setPlaying(false));
  }, [srcUrl]);
  const toggle = () => {
    const a = audio.current;
    if (!a || !srcUrl) return;
    if (a.paused) a.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    else a.pause();
  };
  const seek = (t: number) => {
    playhead.current = t;
    if (audio.current) audio.current.currentTime = t + shift;
  };

  // ---- Chimera
  // the render runs on the server; this follows it until it is done (also one still running when
  // the song is opened again)
  const [job, setJob] = useState<RenderJob | null>(null);
  const follow = useCallback(
    async (first: RenderJob) => {
      // a server from before background renders answers when it is done
      let j: RenderJob = first.state ? first : { ...first, state: "done", progress: 1 };
      setBusy("render");
      setJob(j);
      try {
        while (j.state === "running") {
          await new Promise((r) => setTimeout(r, 400));
          j = await api.renderStatus(s.id);
          setJob(j);
        }
        if (j.state === "done" && j.url) {
          setRender(j.render ?? null);
          setRenderUrl(j.url);
          setSource("chimera");
        } else if (j.state === "error") {
          setMsg({ kind: "error", text: j.error ?? "Chimera could not sing it" });
        }
      } catch (e) {
        setMsg({ kind: "error", text: (e as Error).message });
      } finally {
        setBusy(null);
        setJob(null);
      }
    },
    [s.id],
  );
  useEffect(() => {
    api
      .renderStatus(s.id)
      .then((j) => {
        if (j.state === "running") void follow(j);
      })
      .catch(() => {});
  }, [s.id, follow]);
  const doRender = async () => {
    setBusy("render");
    setMsg(null);
    try {
      clearTimeout(saveTimer.current);
      setJob({ state: "running", progress: 0, elapsed: 0 });
      const r0 = await api.saveNotes(s.id, { notes, body, transpose, vibrato });
      setMelody(r0.melody);
      setWarnings(r0.warnings);
      await follow(await api.render(s.id, body));
    } catch (e) {
      setMsg({ kind: "error", text: (e as Error).message });
      setBusy(null);
      setJob(null);
    }
  };

  // ---- keys
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const k = e.key;
      if (k === " ") toggle();
      else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "z") (e.shiftKey ? redo : undo)();
      else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "y") redo();
      else if (k === "ArrowUp") op.pitch(e.shiftKey ? 12 : 1);
      else if (k === "ArrowDown") op.pitch(e.shiftKey ? -12 : -1);
      else if (k === "ArrowLeft") setSel((i) => (i === null ? 0 : Math.max(0, i - 1)));
      else if (k === "ArrowRight") setSel((i) => (i === null ? 0 : Math.min(notes.length - 1, i + 1)));
      else if (k === "s" || k === "S") op.split();
      else if (k === "Delete" || k === "Backspace") op.merge();
      else if (k === "[") op.shift(-1);
      else if (k === "]") op.shift(1);
      else if (k === "Escape") setSel(null);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const n = sel !== null ? notes[sel] : null;
  const sylOfSel = n ? (n.syl !== null ? s.syllables![n.syl] : "~ (melisma)") : "";
  return (
    <>
      <div className="toolbar">
        <div className="group">
          <button className="play" onClick={toggle} disabled={!srcUrl} title="Space">
            {playing ? "❚❚" : "▶"}
          </button>
          <div className="seg small">
            <button className={source === "original" ? "on" : ""} onClick={() => setSource("original")}>
              Recording
            </button>
            {s.files.vocals && (
              <button className={source === "vocals" ? "on" : ""} onClick={() => setSource("vocals")}>
                Voice
              </button>
            )}
            <button className={source === "chimera" ? "on" : ""} onClick={() => setSource("chimera")} disabled={!renderUrl}>
              Chimera{renderUrl && stale ? " *" : ""}
            </button>
          </div>
        </div>
        <div className="group">
          <label>
            Voice
            <select
              value={body}
              onChange={(e) => {
                setBody(e.target.value);
                save(notes, e.target.value);
              }}
            >
              {BODIES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label title="Semitones, e.g. −12 for a male voice">
            Transpose
            <input
              type="number"
              min={-24}
              max={24}
              value={transpose}
              onChange={(e) => {
                const v = Number(e.target.value) || 0;
                setTranspose(v);
                save(notes, body, v);
              }}
            />
          </label>
          {!spoken && (
            <label title="Vibrato depth in cents">
              Vibrato
              <input
                type="number"
                min={0}
                max={150}
                step={5}
                value={vibrato}
                onChange={(e) => {
                  const v = Number(e.target.value) || 0;
                  setVibrato(v);
                  save(notes, body, transpose, v);
                }}
              />
            </label>
          )}
          <button className="primary" onClick={doRender} disabled={!!busy || !info?.chimera_cli} title={info?.chimera_cli ? "" : "chimera.exe is missing"}>
            {busy === "render"
              ? `Chimera is ${spoken ? "speaking" : "singing"} … ${Math.round((job?.progress ?? 0) * 100)} %`
              : stale
                ? spoken
                  ? "Speak with Chimera"
                  : "Sing with Chimera"
                : spoken
                  ? "Spoken ✓"
                  : "Sung ✓"}
          </button>
        </div>
        <div className="group">
          <button onClick={undo} disabled={!history.past.length} title="Ctrl+Z">
            ↶
          </button>
          <button onClick={redo} disabled={!history.future.length} title="Ctrl+Y">
            ↷
          </button>
          <button
            onClick={() => {
              if (confirm("Restore the converter's original notes?")) commit(s.auto_notes!.map((x) => ({ ...x })));
            }}
          >
            Restore
          </button>
          <button onClick={onReview} title="Change what counts as singing and make the notes again (silences, words cut short)">
            Singing…
          </button>
          <a className="button" href={api.file(s.id, "melody.json")} download={`${s.title}.json`}>
            {spoken ? "Download speech file" : "Download melody"}
          </a>
          <button
            className="primary"
            disabled={spoken}
            title={
              spoken
                ? melodyOnly
                : "Sing it in Chimera's Sing mode, where the voice controls (vibrato, breath, tone, transpose …) work while it sings. Start Chimera with start_chimera.bat."
            }
            onClick={async () => {
              clearTimeout(saveTimer.current);
              const tab = window.open("about:blank", "chimera");
              try {
                await api.saveNotes(s.id, { notes, body, transpose, vibrato });
                const { url } = await api.live(s.id);
                if (tab) tab.location.href = url;
                else window.open(url, "chimera");
              } catch (e) {
                tab?.close();
                setMsg({ kind: "error", text: `Couldn't open it in Chimera: ${(e as Error).message}` });
              }
            }}
          >
            Open in Chimera (live)
          </button>
          <button onClick={() => setShowOpen((v) => !v)} disabled={spoken} title={spoken ? melodyOnly : ""}>
            Duet show…
          </button>
        </div>
      </div>

      {showOpen && <ShowPanel s={s} info={info} stale={stale} onDone={(m) => setMsg(m)} />}
      {job && job.state === "running" && <RenderProgress job={job} />}
      {msg && (
        <div className={`msg ${msg.kind}`}>
          {msg.text}{" "}
          {msg.link && (
            <a href={msg.link} target="_blank" rel="noreferrer">
              {msg.link}
            </a>
          )}
        </div>
      )}

      <div className="roll-box">
        <Roll
          notes={notes}
          contour={s.contour!}
          duration={s.duration ?? 0}
          labels={s.syllables!}
          flagged={flagged}
          doubtful={doubtful}
          focus={focus}
          selected={sel}
          transpose={transpose}
          playhead={playhead}
          playing={playing}
          onSelect={setSel}
          onChange={onRollChange}
          onSeek={seek}
        />
      </div>
      <audio ref={audio} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} preload="auto" />

      <div className="inspector">
        {n ? (
          <>
            <span className="syl">{sylOfSel}</span>
            <span>
              {noteName(n.midi + transpose)} <span className="dim">({(n.midi + transpose).toFixed(1)})</span>
            </span>
            <span className="dim">
              {n.start.toFixed(2)}–{n.end.toFixed(2)} s · {(n.end - n.start).toFixed(2)} s
            </span>
            <button onClick={() => op.pitch(1)}>↑</button>
            <button onClick={() => op.pitch(-1)}>↓</button>
            <button onClick={op.split} disabled={!can.split} title="S: split (at the playhead or in the middle)">
              Split
            </button>
            <button onClick={op.merge} disabled={!can.merge} title="Delete: merge into the previous note">
              Merge into previous
            </button>
            <button onClick={() => op.shift(-1)} disabled={!can.left} title="[: the syllable starts on the previous note">
              ◂ Syllable
            </button>
            <button onClick={() => op.shift(1)} disabled={!can.right} title="]: the syllable starts on the next note">
              Syllable ▸
            </button>
            {flagged.has(sel!) && <span className="warn">Melisma inside a word: Chimera merges it into the previous note.</span>}
            {doubtful.has(sel!) && (
              <span className="warn">
                No singing found for this syllable: check its place.{" "}
                <button onClick={() => setDoubtSyl((d) => new Set([...d].filter((k) => k !== n!.syl)))}>Looks right</button>
              </span>
            )}
          </>
        ) : (
          <span className="dim">
            Select a note. Drag up/down: pitch · edges: timing · Shift+drag: move · S split · Delete merge · [ ] move syllable · wheel
            scrolls, Ctrl+wheel zooms · Space plays.
          </span>
        )}
      </div>
      <div className="status">
        <span>
          {notes.length} notes · {nSyl} syllables · {notes.filter((x) => x.syl === null).length} melisma
        </span>
        {doubtful.size > 0 && (
          <button className="doubt" onClick={nextDoubt} title="Syllables that found no singing to sit on">
            {doubtful.size} to check ▸
          </button>
        )}
        {s.tuning_cents ? <span title="The singer's tuning relative to A440; the notes follow it">tuning {s.tuning_cents > 0 ? "+" : ""}{s.tuning_cents} c</span> : null}
        <span className="legend">
          <i className="sw blue" /> syllable <i className="sw pink" /> melisma <i className="sw doubt" /> to check <i className="sw amber" /> sung pitch
        </span>
        {warnings.map((w) => (
          <span key={w} className="warn">
            {w}
          </span>
        ))}
      </div>
    </>
  );
}

function ShowPanel({ s, info, stale, onDone }: { s: Session; info: Info | null; stale: boolean; onDone: (m: { kind: "ok" | "error"; text: string; link?: string }) => void }) {
  const [id, setId] = useState(s.title.toLowerCase().normalize("NFKD").replace(/[^\w-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "song");
  const [mix, setMix] = useState("both");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const r = await api.show(s.id, id, mix, s.title);
      onDone({
        kind: "ok",
        text: `Show saved to ${r.dir}.${r.words ? "" : " No words by the mouth: the duet page reads English only."} Open it in Chimera (run start_chimera.bat):`,
        link: r.url,
      });
    } catch (e) {
      onDone({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel show-panel">
      <b>Send to Chimera's duet page</b>
      <label>
        Show id
        <input value={id} onChange={(e) => setId(e.target.value.toLowerCase())} />
      </label>
      <div className="seg small">
        {[
          ["chimera", "Chimera only"],
          ["both", "Chimera + recording"],
          ["original", "Recording only"],
        ].map(([v, l]) => (
          <button key={v} className={mix === v ? "on" : ""} onClick={() => setMix(v)}>
            {l}
          </button>
        ))}
      </div>
      <button className="primary" onClick={go} disabled={busy || stale || !info?.repo}>
        {busy ? "Sending …" : "Send"}
      </button>
      {stale && <span className="warn">Sing the current notes with Chimera first.</span>}
      <span className="dim">Folder {info?.shows}\{id} (kept out of git)</span>
    </div>
  );
}

const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

/** Chimera singing the song: an estimate (the time a second of song took last time), so it says
 * "about" and slows near the end rather than claiming it is done. */
function RenderProgress({ job }: { job: RenderJob }) {
  const p = job.progress ?? 0;
  const left = job.expected !== undefined && job.elapsed !== undefined ? Math.max(0, job.expected - job.elapsed) : null;
  return (
    <div className="render-progress" role="status" aria-live="polite">
      <div className="progress-head">
        <i className="pulse" />
        <b>Chimera is singing the song</b>
        <span>{Math.round(p * 100)} %</span>
        <span className="dim">
          {mmss(job.elapsed ?? 0)}
          {left !== null && job.expected ? (left > 0 ? ` · about ${mmss(left + 1)} left` : " · almost done") : ""}
          {job.length ? ` · ${mmss(job.length)} of song` : ""}
        </span>
      </div>
      <div className="bar live">
        <div style={{ width: `${Math.max(2, Math.round(p * 100))}%` }} />
      </div>
    </div>
  );
}
