import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Session, type Singing, type SingingData } from "./api.ts";

/**
 * What counts as singing, checked before the notes are made: the voice's level and pitch clarity
 * over the song, the thresholds on them, and what they find (green: singing, pale: a gap held as
 * part of the syllable, grey: loud but left out). Click the picture to listen from there.
 * The same rule as the server's (transcribe.frames_from), so what you see is what the notes get.
 */
export function SingingCheck({ s, onQueued }: { s: Session; onQueued: () => void }) {
  const [data, setData] = useState<SingingData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [v, setV] = useState<Singing | null>(null);
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    let live = true;
    api
      .singing(s.id)
      .then((d) => {
        if (!live) return;
        setData(d);
        setV(d.current);
      })
      .catch((e) => live && setErr((e as Error).message));
    return () => {
      live = false;
    };
  }, [s.id]);

  const found = useMemo(() => (data && v ? classify(data, v) : null), [data, v]);

  if (err) return <div className="panel error">{err}</div>;
  if (!data || !v || !found) return <div className="panel dim">Loading the analysis …</div>;

  const set = (k: keyof Singing, x: number) => setV({ ...v, [k]: x });
  const go = async () => {
    setBusy(true);
    try {
      await api.setSinging(s.id, v);
      onQueued();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };
  const back = async () => {
    setBusy(true);
    try {
      await api.review(s.id, true);
      onQueued();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };
  const play = (t: number) => {
    const a = audio.current;
    if (!a) return;
    a.currentTime = t;
    void a.play();
  };
  const same = JSON.stringify(v) === JSON.stringify(data.suggested);

  return (
    <div className="panel singing-check">
      <div className="progress-head">
        <b>What counts as singing</b>
        <span className="dim">Set these before the notes are made: a syllable can only sit where singing is found.</span>
      </div>

      <div className="singing-stats">
        <span>
          Singing found: <b>{mmss(found.sung)}</b> of {mmss(data.duration)} ({Math.round((100 * found.sung) / Math.max(1, data.duration))} %)
        </span>
        <span>
          in <b>{found.stretches}</b> stretches
        </span>
        {data.syllables !== null && (
          <span>
            · the lyrics have <b>{data.syllables}</b> syllables
          </span>
        )}
        {found.missed > 0.5 && (
          <span className="warn">
            · loud but left out: <b>{mmss(found.missed)}</b>
          </span>
        )}
      </div>

      <Timeline data={data} v={v} found={found} zoom={zoom} pos={pos} onPick={play} />

      <div className="singing-legend">
        <span>
          <i className="sw sing" /> singing
        </span>
        <span>
          <i className="sw held" /> gap held in the syllable
        </span>
        <span>
          <i className="sw miss" /> loud, not counted
        </span>
        <span>
          <i className="sw lvl" /> level · <i className="sw gate" /> level threshold
        </span>
        <span>
          <i className="sw clr" /> pitch clarity
        </span>
        <span className="zoom">
          Zoom
          {[1, 2, 4, 8].map((z) => (
            <button key={z} className={z === zoom ? "on" : ""} onClick={() => setZoom(z)}>
              {z}×
            </button>
          ))}
        </span>
      </div>
      <audio ref={audio} src={api.file(s.id, data.audio)} controls preload="none" onTimeUpdate={(e) => setPos(e.currentTarget.currentTime)} onPause={(e) => setPos(e.currentTarget.currentTime)} />

      <div className="singing-controls">
        <Slider
          label="Level threshold"
          hint="Singing is louder than this (dB below the loudest moment). Lower it if quiet singing is missed; raise it if backing or breaths count."
          min={-60}
          max={-10}
          step={1}
          value={v.gate_db}
          shown={`${Math.round(v.gate_db)} dB`}
          onChange={(x) => set("gate_db", x)}
        />
        <Slider
          label="Pitch clarity needed"
          hint="How clear a pitch must be to count. Lower it for breathy or reverberant singing."
          min={0}
          max={0.6}
          step={0.01}
          value={v.clarity}
          shown={v.clarity.toFixed(2)}
          onChange={(x) => set("clarity", x)}
        />
        <Slider
          label="Rough voice counts"
          hint={
            data.voice_only
              ? "Loud singing without a clear pitch (shouted, rasped, distorted) counts as singing this much. Its pitch is the tracker's best guess."
              : "This recording was not separated: the band is loud too, so keep this at 0 unless the recording is a voice alone."
          }
          min={0}
          max={1}
          step={0.05}
          value={v.rough}
          shown={`${Math.round(v.rough * 100)} %`}
          onChange={(x) => set("rough", x)}
        />
        <Slider
          label="Hold syllables over gaps"
          hint="A gap shorter than this is a consonant, not a rest: the syllable is held over it (words don't come out short). At a line break the singer still breathes."
          min={0}
          max={1.2}
          step={0.05}
          value={v.hold}
          shown={`${v.hold.toFixed(2)} s`}
          onChange={(x) => set("hold", x)}
        />
      </div>

      <div className="singing-actions">
        <button className="primary big" onClick={go} disabled={busy}>
          Make the notes →
        </button>
        <button onClick={() => setV(data.suggested)} disabled={busy || same} title="The values suggested for this recording">
          Suggested values
        </button>
        {data.has_notes && (
          <button onClick={back} disabled={busy} title="Keep the notes you had">
            Back to the notes
          </button>
        )}
        {data.has_notes && <span className="dim">Making the notes again replaces your edits.</span>}
      </div>
    </div>
  );
}

function Slider(props: { label: string; hint: string; min: number; max: number; step: number; value: number; shown: string; onChange: (x: number) => void }) {
  return (
    <label className="slider" title={props.hint}>
      <span className="slider-head">
        <span>{props.label}</span>
        <b>{props.shown}</b>
      </span>
      <input type="range" min={props.min} max={props.max} step={props.step} value={props.value} onChange={(e) => props.onChange(Number(e.target.value))} />
      <span className="dim slider-hint">{props.hint}</span>
    </label>
  );
}

interface Found {
  /** per frame: 0 nothing, 1 singing, 2 held gap, 3 loud but not counted */
  kind: Uint8Array;
  sung: number;
  missed: number;
  stretches: number;
}

/** transcribe.frames_from's voicing, and the gaps hold_over_gaps would close */
function classify(d: SingingData, v: Singing): Found {
  const n = d.db.length;
  const kind = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    const loud = Math.min(1, Math.max(0, (d.db[i] - v.gate_db) / 8));
    const clear = Math.min(1, Math.max(0, (d.clarity[i] - v.clarity) / 0.45));
    const voiced = loud * Math.max(clear, v.rough);
    kind[i] = voiced >= 0.3 ? 1 : d.db[i] > v.gate_db + 8 ? 3 : 0;
  }
  // gaps shorter than `hold` between singing are held
  const maxGap = Math.round(v.hold / d.hop);
  let last = -1;
  for (let i = 0; i < n; i++) {
    if (kind[i] !== 1) continue;
    if (last >= 0 && i - last - 1 > 0 && i - last - 1 < maxGap) for (let j = last + 1; j < i; j++) kind[j] = 2;
    last = i;
  }
  let sung = 0, missed = 0, stretches = 0;
  for (let i = 0; i < n; i++) {
    if (kind[i] === 1 || kind[i] === 2) {
      sung += d.hop;
      if (i === 0 || (kind[i - 1] !== 1 && kind[i - 1] !== 2)) stretches++;
    } else if (kind[i] === 3) missed += d.hop;
  }
  return { kind, sung, missed, stretches };
}

const COL = { bg: "#000", frame: "#133954", lvl: "#3487c4", gate: "#ffb340", clr: "#1f5f8c", sing: "#5be381", held: "#2f7a47", miss: "#7a6a52", pos: "#eef6f8", text: "#3487c4" };

function Timeline(props: { data: SingingData; v: Singing; found: Found; zoom: number; pos: number | null; onPick: (t: number) => void }) {
  const { data, v, found, zoom, pos } = props;
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [w, setW] = useState(800);
  useEffect(() => {
    const el = wrap.current!;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const W = Math.max(200, Math.round(w * zoom));
  const H = 220;
  // keep the playhead in view while it plays
  useEffect(() => {
    const el = wrap.current;
    if (!el || pos === null || zoom === 1) return;
    const x = (pos / data.duration) * W;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 20) el.scrollLeft = x - el.clientWidth / 3;
  }, [pos, zoom, W, data.duration]);
  useEffect(() => {
    const c = cv.current!;
    const dpr = window.devicePixelRatio || 1;
    c.width = W * dpr;
    c.height = H * dpr;
    const g = c.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = COL.bg;
    g.fillRect(0, 0, W, H);
    const n = data.db.length;
    const X = (i: number) => (i / n) * W;
    // lanes: result strip, level, clarity
    const r0 = 4, r1 = 24, l0 = 32, l1 = 160, c0 = 168, c1 = H - 14;
    const DB0 = -66;
    const yl = (db: number) => l1 - ((Math.max(DB0, Math.min(0, db)) - DB0) / -DB0) * (l1 - l0);
    // seconds grid
    g.strokeStyle = COL.frame;
    g.fillStyle = COL.text;
    g.font = "10px Archivo, sans-serif";
    const step = data.duration / zoom > 120 ? 30 : data.duration / zoom > 40 ? 10 : 5;
    for (let t = 0; t <= data.duration; t += step) {
      const x = (t / data.duration) * W;
      g.beginPath();
      g.moveTo(x + 0.5, l0);
      g.lineTo(x + 0.5, c1);
      g.stroke();
      g.fillText(mmss(t), x + 3, H - 3);
    }
    // the result strip
    for (let i = 0; i < n; i++) {
      const k = found.kind[i];
      if (!k) continue;
      g.fillStyle = k === 1 ? COL.sing : k === 2 ? COL.held : COL.miss;
      g.fillRect(X(i), k === 3 ? r0 + 12 : r0, Math.max(1, W / n + 0.5), k === 3 ? r1 - r0 - 12 : r1 - r0);
    }
    // level
    g.beginPath();
    g.moveTo(0, l1);
    for (let i = 0; i < n; i++) g.lineTo(X(i), yl(data.db[i]));
    g.lineTo(W, l1);
    g.closePath();
    g.fillStyle = "rgba(52,135,196,0.35)";
    g.fill();
    g.strokeStyle = COL.lvl;
    g.lineWidth = 1;
    g.stroke();
    // level threshold
    g.strokeStyle = COL.gate;
    g.setLineDash([6, 4]);
    g.beginPath();
    g.moveTo(0, yl(v.gate_db) + 0.5);
    g.lineTo(W, yl(v.gate_db) + 0.5);
    g.stroke();
    g.setLineDash([]);
    // clarity
    for (let i = 0; i < n; i++) {
      const hgt = data.clarity[i] * (c1 - c0);
      if (hgt < 0.5) continue;
      g.fillStyle = data.clarity[i] >= v.clarity ? COL.lvl : COL.clr;
      g.fillRect(X(i), c1 - hgt, Math.max(1, W / n + 0.5), hgt);
    }
    g.strokeStyle = COL.gate;
    g.setLineDash([3, 3]);
    g.beginPath();
    const yc = c1 - v.clarity * (c1 - c0);
    g.moveTo(0, yc + 0.5);
    g.lineTo(W, yc + 0.5);
    g.stroke();
    g.setLineDash([]);
    // playhead
    if (pos !== null) {
      const x = (pos / data.duration) * W;
      g.strokeStyle = COL.pos;
      g.beginPath();
      g.moveTo(x + 0.5, 0);
      g.lineTo(x + 0.5, H);
      g.stroke();
    }
  }, [data, v, found, W, pos, zoom]);
  return (
    <div className="singing-timeline" ref={wrap}>
      <canvas
        ref={cv}
        style={{ width: W, height: H }}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          props.onPick(((e.clientX - r.left) / r.width) * data.duration);
        }}
        title="Click to listen from here"
      />
    </div>
  );
}

const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
