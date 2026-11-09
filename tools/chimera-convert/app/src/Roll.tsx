import { useEffect, useRef } from "react";
import { moveEdge, moveNote, noteName, setPitch, type Note } from "./edit.ts";

const C = {
  bg: "#000000",
  rowDark: "#05101a",
  frame: "#133954",
  blue: "#4fb6f2",
  blueDim: "#1f5f8c",
  amber: "#ffb340",
  pink: "#ff73cf",
  red: "#ff5d40",
  white: "#eef6f8",
  green: "#5be381",
};
const BLACK = new Set([1, 3, 6, 8, 10]);
const RULER = 22;
const GUTTER = 46;
const EDGE = 6;

export interface RollProps {
  notes: Note[];
  contour: { hop: number; midi: (number | null)[] };
  duration: number;
  labels: string[];
  /** note indexes Chimera can't sing as they are (drawn red) */
  flagged: Set<number>;
  /** notes whose syllable found no singing (drawn amber, dashed) */
  doubtful: Set<number>;
  /** bring this time into view when it changes */
  focus: { t: number } | null;
  selected: number | null;
  transpose: number;
  playhead: React.MutableRefObject<number>;
  playing: boolean;
  onSelect: (i: number | null) => void;
  /** a drag in progress (commit false) or finished (commit true) */
  onChange: (notes: Note[], commit: boolean) => void;
  onSeek: (t: number) => void;
}

type Drag = { kind: "start" | "end" | "pitch" | "move"; i: number; x0: number; y0: number; orig: Note[]; moved: boolean };

/** The piano roll: the sung pitch (amber), the notes with their syllables, the playhead. Drag a
 * note up or down for its pitch, its edges for its timing, Shift-drag to move it; the wheel
 * scrolls and Ctrl+wheel zooms. */
export function Roll(p: RollProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef({ t0: 0, pps: 120, lo: 48, hi: 84, w: 0, h: 0, fitted: false });
  const drag = useRef<Drag | null>(null);
  const props = useRef(p);
  props.current = p;

  // pitch range from the contour and the notes
  useEffect(() => {
    const vals = p.contour.midi.filter((v): v is number => v !== null).concat(p.notes.map((n) => n.midi));
    if (!vals.length) return;
    const sorted = [...vals].sort((a, b) => a - b);
    const q = (f: number) => sorted[Math.floor(f * (sorted.length - 1))];
    const v = view.current;
    v.lo = Math.floor(Math.min(q(0.01), ...p.notes.map((n) => n.midi)) + p.transpose) - 3;
    v.hi = Math.ceil(Math.max(q(0.99), ...p.notes.map((n) => n.midi)) + p.transpose) + 3;
    if (v.hi - v.lo < 14) {
      const c = (v.hi + v.lo) / 2;
      v.lo = Math.floor(c - 7);
      v.hi = Math.ceil(c + 7);
    }
  }, [p.contour, p.notes.length, p.transpose]);

  useEffect(() => {
    const cv = canvas.current!;
    const ro = new ResizeObserver(() => {
      const r = cv.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(r.width * dpr);
      cv.height = Math.round(r.height * dpr);
      const v = view.current;
      v.w = r.width;
      v.h = r.height;
      if (!v.fitted && props.current.duration > 0) {
        v.pps = Math.max(40, Math.min(200, (r.width - GUTTER) / Math.min(props.current.duration, 20)));
        v.fitted = true;
      }
    });
    ro.observe(cv);
    let raf = 0;
    const loop = () => {
      draw();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);

  const X = (t: number) => GUTTER + (t - view.current.t0) * view.current.pps;
  const T = (x: number) => view.current.t0 + (x - GUTTER) / view.current.pps;
  const Y = (m: number) => {
    const v = view.current;
    return RULER + ((v.hi - m) / (v.hi - v.lo)) * (v.h - RULER);
  };
  const M = (y: number) => {
    const v = view.current;
    return v.hi - ((y - RULER) / (v.h - RULER)) * (v.hi - v.lo);
  };
  const rowH = () => (view.current.h - RULER) / (view.current.hi - view.current.lo);

  function draw() {
    const cv = canvas.current;
    if (!cv) return;
    const ctx = cv.getContext("2d")!;
    const v = view.current;
    const P = props.current;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, v.w, v.h);
    // follow the playhead
    if (P.playing && !drag.current) {
      const x = X(P.playhead.current);
      if (x > v.w - 60 || x < GUTTER) v.t0 = Math.max(0, P.playhead.current - 1);
    }
    const rh = rowH();
    // semitone rows
    for (let m = Math.floor(v.lo); m <= v.hi; m++) {
      const y = Y(m + 0.5);
      if (BLACK.has(((m % 12) + 12) % 12)) {
        ctx.fillStyle = C.rowDark;
        ctx.fillRect(GUTTER, y, v.w - GUTTER, rh);
      }
      if (((m % 12) + 12) % 12 === 0) {
        ctx.strokeStyle = C.frame;
        ctx.beginPath();
        ctx.moveTo(GUTTER, Y(m - 0.5) + 0.5);
        ctx.lineTo(v.w, Y(m - 0.5) + 0.5);
        ctx.stroke();
      }
    }
    // seconds
    const step = v.pps > 60 ? 1 : v.pps > 20 ? 5 : 10;
    ctx.font = "11px Archivo, system-ui, sans-serif";
    ctx.textBaseline = "middle";
    for (let s = Math.ceil(v.t0 / step) * step; X(s) < v.w; s += step) {
      const x = Math.round(X(s)) + 0.5;
      ctx.strokeStyle = C.frame;
      ctx.beginPath();
      ctx.moveTo(x, RULER);
      ctx.lineTo(x, v.h);
      ctx.stroke();
      ctx.fillStyle = C.blueDim;
      ctx.fillText(`${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`, x + 3, RULER / 2);
    }
    // the sung pitch
    const { hop, midi } = P.contour;
    const i0 = Math.max(0, Math.floor(v.t0 / hop));
    const i1 = Math.min(midi.length, Math.ceil(T(v.w) / hop) + 1);
    ctx.strokeStyle = C.amber;
    ctx.globalAlpha = 0.75;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    let pen = false;
    for (let i = i0; i < i1; i++) {
      const m = midi[i];
      if (m === null) {
        pen = false;
        continue;
      }
      const x = X(i * hop), y = Y(m + P.transpose);
      if (pen) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      pen = true;
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.lineWidth = 1;
    // notes
    ctx.font = "12px Archivo, system-ui, sans-serif"; // Hershey has no ä/ö
    ctx.textBaseline = "bottom";
    P.notes.forEach((n, i) => {
      const x0 = X(n.start), x1 = X(n.end);
      if (x1 < GUTTER || x0 > v.w) return;
      const m = Math.round(n.midi + P.transpose);
      const y = Y(m + 0.5);
      const doubt = P.doubtful.has(i);
      const col = P.flagged.has(i) ? C.red : doubt ? C.amber : n.syl === null ? C.pink : C.blue;
      ctx.fillStyle = col;
      ctx.globalAlpha = 0.28;
      ctx.fillRect(x0, y + 1, x1 - x0, rh - 2);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = i === P.selected ? C.white : col;
      ctx.lineWidth = i === P.selected ? 2 : 1;
      if (doubt) ctx.setLineDash([3, 2]);
      ctx.strokeRect(x0 + 0.5, y + 1.5, x1 - x0 - 1, rh - 3);
      ctx.setLineDash([]);
      ctx.lineWidth = 1;
      ctx.fillStyle = i === P.selected ? C.white : n.syl === null ? C.pink : C.green;
      ctx.fillText(n.syl === null ? "~" : P.labels[n.syl] ?? "?", x0 + 2, y - 1);
    });
    // gutter: note names
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, RULER, GUTTER, v.h);
    ctx.textBaseline = "middle";
    ctx.font = "10px Archivo, system-ui, sans-serif";
    for (let m = Math.ceil(v.lo); m <= v.hi; m++) {
      const pc = ((m % 12) + 12) % 12;
      if (rh < 9 && pc !== 0) continue;
      ctx.fillStyle = pc === 0 ? C.blue : BLACK.has(pc) ? C.blueDim : "#2a6d9c";
      ctx.fillText(noteName(m), 4, Y(m));
    }
    ctx.strokeStyle = C.frame;
    ctx.beginPath();
    ctx.moveTo(GUTTER + 0.5, RULER);
    ctx.lineTo(GUTTER + 0.5, v.h);
    ctx.moveTo(0, RULER + 0.5);
    ctx.lineTo(v.w, RULER + 0.5);
    ctx.stroke();
    // playhead
    const px = X(P.playhead.current);
    if (px >= GUTTER && px <= v.w) {
      ctx.strokeStyle = C.white;
      ctx.beginPath();
      ctx.moveTo(Math.round(px) + 0.5, 0);
      ctx.lineTo(Math.round(px) + 0.5, v.h);
      ctx.stroke();
    }
  }

  function hit(x: number, y: number): { i: number; zone: "start" | "end" | "body" } | null {
    const P = props.current;
    const rh = rowH();
    for (let i = P.notes.length - 1; i >= 0; i--) {
      const n = P.notes[i];
      const x0 = X(n.start), x1 = X(n.end), yy = Y(Math.round(n.midi + P.transpose) + 0.5);
      if (y < yy - 2 || y > yy + rh + 2 || x < x0 - 3 || x > x1 + 3) continue;
      const w = x1 - x0;
      if (x - x0 < Math.min(EDGE, w / 3)) return { i, zone: "start" };
      if (x1 - x < Math.min(EDGE, w / 3)) return { i, zone: "end" };
      return { i, zone: "body" };
    }
    return null;
  }

  const pos = (e: React.PointerEvent | React.WheelEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const onDown = (e: React.PointerEvent) => {
    const { x, y } = pos(e);
    const P = props.current;
    if (y < RULER || x < GUTTER) {
      if (x >= GUTTER) P.onSeek(Math.max(0, T(x)));
      return;
    }
    const h = hit(x, y);
    if (!h) {
      P.onSelect(null);
      P.onSeek(Math.max(0, T(x)));
      return;
    }
    P.onSelect(h.i);
    canvas.current!.setPointerCapture(e.pointerId);
    drag.current = { kind: h.zone === "body" ? (e.shiftKey ? "move" : "pitch") : h.zone, i: h.i, x0: x, y0: y, orig: P.notes, moved: false };
  };

  const onMove = (e: React.PointerEvent) => {
    const { x, y } = pos(e);
    const d = drag.current;
    const cv = canvas.current!;
    if (!d) {
      const h = y > RULER && x > GUTTER ? hit(x, y) : null;
      cv.style.cursor = !h ? "crosshair" : h.zone === "body" ? (e.shiftKey ? "grab" : "ns-resize") : "ew-resize";
      return;
    }
    if (!d.moved && Math.abs(x - d.x0) < 3 && Math.abs(y - d.y0) < 3) return;
    d.moved = true;
    const P = props.current;
    let ns: Note[];
    if (d.kind === "pitch") ns = setPitch(d.orig, d.i, Math.round(d.orig[d.i].midi + (M(y) - M(d.y0))));
    else if (d.kind === "move") ns = moveNote(d.orig, d.i, (x - d.x0) / view.current.pps);
    else ns = moveEdge(d.orig, d.i, d.kind, T(x));
    P.onChange(ns, false);
  };

  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.moved) props.current.onChange(props.current.notes, true);
  };

  const onWheel = (e: React.WheelEvent) => {
    const v = view.current;
    const { x } = pos(e);
    if (e.ctrlKey || e.metaKey) {
      const t = T(x);
      v.pps = Math.max(8, Math.min(800, v.pps * Math.exp(-e.deltaY * 0.0015)));
      v.t0 = Math.max(0, t - (x - GUTTER) / v.pps);
    } else {
      const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      v.t0 = Math.max(0, Math.min(props.current.duration, v.t0 + d / v.pps));
    }
  };

  useEffect(() => {
    if (!p.focus) return;
    const v = view.current;
    const span = (v.w - GUTTER) / v.pps;
    if (p.focus.t < v.t0 || p.focus.t > v.t0 + span * 0.85) v.t0 = Math.max(0, p.focus.t - span * 0.3);
  }, [p.focus]);

  // keep the page from scrolling under the roll (wheel listeners from React are passive)
  useEffect(() => {
    const cv = canvas.current!;
    const stop = (e: WheelEvent) => e.preventDefault();
    cv.addEventListener("wheel", stop, { passive: false });
    return () => cv.removeEventListener("wheel", stop);
  }, []);

  return <canvas ref={canvas} className="roll" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onWheel={onWheel} />;
}
