/**
 * The duet page (`?show=<id>`): a pre-rendered song with two (or more) voices, each on its own 3D
 * head, side by side, moving exactly as the engine did when it sang. Nothing is synthesized here:
 * the page plays the mixed track and replays each voice's recorded telemetry at the playhead.
 *
 * A show is a folder `public/shows/<id>/` (gitignored: shows are made locally, often of songs that
 * mustn't be published) holding `show.json`, the mix and one `.tele` per voice from
 * `chimera render notes … --tele`. The voices' renders and the mix must share sample 0.
 *
 *   { "title": "…", "audio": "mix.mp3", "bpm": 103, "downbeat": 0,
 *     "voices": [{ "name": "Lower", "tele": "male.tele" }, { "name": "Upper", "tele": "female.tele" }] }
 *
 * Optional: `bpm` and `downbeat` (s, a bar's first beat) nod the heads on the beat; a voice's
 * `melody` (the melody file it was rendered from) writes its words at its mouth, split into
 * syllables by its `"lang"` (Finnish rules for "fi", the English dictionary otherwise, as the CLI
 * sang them), and the show's `spell` ({"owr": "our"}) writes a syllable spelled for the dictionary
 * as it should read.
 *
 * A show of one voice with its melody can also be sung live (the default then): the engine sings
 * the melody here, with the voice panel's settings heard as they change, over the show's `backing`
 * (the recording without its voice, on the same clock as the melody) when it has one.
 */
import { useEffect, useRef, useState } from "react";
import { AnatomyView3D, type HeadFeed } from "./AnatomyView3D.tsx";
import { Screen } from "./Screen.tsx";
import { TeleTrack } from "../../show/tele.ts";
import { Transport } from "../../show/transport.ts";
import { getModel } from "../useModel.ts";
import { VoiceModel } from "../analysis.ts";
import { bodyLabel } from "../body.ts";
import type { ViewFlags } from "../render/anatomy.ts";
import { mouthWords } from "../mouthWords.ts";
import { V } from "../colors.ts";
import { g2p } from "../speech.ts";
import { lyricsToSyllables, finnishLyricsToSyllables } from "../../wasm/engine.ts";
import { sungWords, wordAt, type Melody, type SungWords } from "../../show/words.ts";
import type { OverlayFn } from "./AnatomyView.tsx";
import { LiveShow } from "../liveShow.ts";
import { LiveVoicePanel } from "./LiveVoicePanel.tsx";
import { engine } from "../../audio/AudioEngine.ts";
import { useStore } from "../store.ts";
import { PRESETS, sameBody } from "../body.ts";
import { applyStyle, showStyle } from "../voiceStyle.ts";
import type { SongFile } from "../singing.ts";

interface ShowFile {
  title: string;
  audio: string;
  /** the recording without its voice, for the live voice to sing over */
  backing?: string;
  bpm?: number;
  downbeat?: number;
  spell?: Record<string, string>;
  voices: { name: string; tele: string; melody?: string; hair?: boolean }[];
}

interface Loaded {
  show: ShowFile;
  voices: { name: string; track: TeleTrack; words: SungWords | null }[];
  /** what a live voice sings: the only voice's melody */
  melody: Melody | null;
  backing: ArrayBuffer | null;
}

/** what the bar and the heads follow: the recorded show's transport or the live one */
interface Player {
  readonly isPlaying: boolean;
  readonly duration: number;
  readonly epoch: number;
  time(): number;
  play(): void | Promise<void>;
  pause(): void;
  seek(t: number): void;
  subscribe(f: () => void): () => void;
}

const LIVE_KEY = "chimera.duetLive";
function liveWanted(): boolean {
  try {
    return localStorage.getItem(LIVE_KEY) !== "0";
  } catch {
    return true;
  }
}

/** the heads as the face screen shows them by default, less the measurement labels */
const VIEW: ViewFlags = { pressure: true, particles: true, grid: false, calipers: false };

async function fetchOk(url: string): Promise<Response> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status} ${r.statusText}`);
  return r;
}

const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

export function DuetPage(props: { id: string }) {
  const base = `${import.meta.env.BASE_URL}shows/${props.id}/`;
  // one transport per mount (its context closes on unmount)
  const [transport, setTransport] = useState<Transport | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    const t = new Transport();
    setTransport(t);
    return () => t.dispose();
  }, []);

  useEffect(() => {
    if (!transport) return;
    let live = true;
    setLoaded(null);
    (async () => {
      const show = (await (await fetchOk(base + "show.json")).json()) as ShowFile;
      if (!show.voices?.length || !show.audio) throw new Error("show.json needs audio and voices");
      const [audio, ...teles] = await Promise.all([fetchOk(base + show.audio).then((r) => r.arrayBuffer()), ...show.voices.map((v) => fetchOk(base + v.tele).then((r) => r.arrayBuffer()))]);
      // the words: syllables as the CLI splits them: Finnish lyrics by the Finnish rules (English
      // ones split "käyn" at the ä and their count missed the notes, so a Finnish voice showed
      // nothing), English by the pronouncing dictionary first, as it does
      const melodies = await Promise.all(show.voices.map((v) => (v.melody ? fetchOk(base + v.melody).then((r) => r.json() as Promise<Melody>) : null)));
      const finnish = (m: Melody) => m.lang === "fi";
      if (melodies.some((m) => m && !finnish(m))) await g2p.load().catch(() => {});
      const words = melodies.map((m) => {
        if (!m) return null;
        try {
          return sungWords(m, finnish(m) ? finnishLyricsToSyllables(m.lyrics) : lyricsToSyllables(m.lyrics), show.spell);
        } catch (e) {
          console.warn("duet: no words for a voice:", e);
          return null;
        }
      });
      const voices = show.voices.map((v, i) => ({ name: v.name, track: new TeleTrack(teles[i]), words: words[i] }));
      await transport.load(audio);
      const melody = show.voices.length === 1 && words[0] ? melodies[0] : null;
      const backing = melody && show.backing ? await fetchOk(base + show.backing).then((r) => r.arrayBuffer()).catch(() => null) : null;
      if (live) setLoaded({ show, voices, melody, backing });
    })().catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [base, transport]);

  // the live voice: the engine sings the melody with the voice panel's settings
  const [liveOn, setLiveOn] = useState(liveWanted);
  const [panel, setPanel] = useState(true);
  const [live, setLive] = useState<LiveShow | null>(null);
  const canLive = !!loaded?.melody;
  useEffect(() => {
    if (!loaded?.melody || !liveOn) return;
    let ls: LiveShow;
    try {
      ls = new LiveShow(loaded.melody as SongFile, loaded.backing, loaded.show.title);
    } catch (e) {
      console.warn("duet: can't sing this show live:", e);
      return;
    }
    // the voice this show was last sung with
    const kept = showStyle(props.id);
    const sungAs = (loaded.melody as { body?: string }).body;
    if (kept) applyStyle(kept);
    else if (sungAs === "male" || sungAs === "female" || sungAs === "child") applyStyle({ body: PRESETS[sungAs] });
    transport?.pause();
    setLive(ls);
    return () => {
      ls.dispose();
      setLive(null);
    };
  }, [loaded, liveOn, props.id, transport]);
  const useLive = liveOn && !!live;
  const player: Player | null = useLive ? live : transport;
  const switchLive = (on: boolean) => {
    try {
      localStorage.setItem(LIVE_KEY, on ? "1" : "0");
    } catch {
      // not kept
    }
    setLiveOn(on);
  };

  // the readouts follow the player: at once on a change, and a few times a second while it plays
  useEffect(() => {
    if (!player) return;
    const off = player.subscribe(() => setTick((n) => n + 1));
    const id = setInterval(() => player.isPlaying && setTick((n) => n + 1), 250);
    return () => {
      off();
      clearInterval(id);
    };
  }, [player]);

  if (error)
    return (
      <div className="duet">
        <p className="duet-msg error">This show could not load: {error}</p>
      </div>
    );
  const st = player ? { playing: player.isPlaying, time: player.time(), duration: player.duration } : { playing: false, time: 0, duration: 0 };
  const title = loaded?.show.title ?? "Loading…";
  const showPanel = useLive && panel;
  return (
    <div className={`duet${showPanel ? " with-voice" : ""}`}>
      <header className="duet-top">
        <span className="wordmark">Chimera</span>
        <span className="duet-title">{title}</span>
        {canLive && (
          <div className="duet-modes" role="group" aria-label="Who sings">
            <button type="button" className={`enc-tab${!liveOn ? " on" : ""}`} aria-pressed={!liveOn} onClick={() => switchLive(false)} title="The render as it was made">
              Recorded
            </button>
            <button type="button" className={`enc-tab${liveOn ? " on" : ""}`} aria-pressed={liveOn} onClick={() => switchLive(true)} title="Chimera sings it here, with your voice settings">
              Live voice
            </button>
            {liveOn && (
              <button type="button" className={`enc-tab${panel ? " on" : ""}`} aria-pressed={panel} onClick={() => setPanel(!panel)}>
                Voice settings
              </button>
            )}
          </div>
        )}
      </header>
      <main className="duet-heads" style={{ "--voices": loaded?.voices.length ?? 2 } as React.CSSProperties}>
        {loaded && transport ? (
          useLive && live ? (
            <LiveHead name={loaded.voices[0].name} words={loaded.voices[0].words} live={live} />
          ) : (
            loaded.voices.map((v, i) => <Head key={i} name={v.name} track={v.track} words={v.words} show={loaded.show} transport={transport} facing={i > 0 && i === loaded.voices.length - 1 ? -1 : 1} hair={loaded.show.voices[i]?.hair} />)
          )
        ) : (
          <p className="duet-msg">Loading the song…</p>
        )}
      </main>
      {showPanel && live && <LiveVoicePanel showId={props.id} live={live} />}
      <footer className="duet-bar">
        <button className="primary large" disabled={!loaded} onClick={() => (st.playing ? player?.pause() : void player?.play())}>
          {st.playing ? "Pause" : st.duration > 0 && st.time >= st.duration - 0.05 ? "Again" : "Play"}
        </button>
        <span className="duet-time">
          {clock(st.time)} / {clock(st.duration)}
        </span>
        <input
          type="range"
          aria-label="Position in the song"
          min={0}
          max={st.duration || 1}
          step={0.1}
          value={st.time}
          disabled={!loaded}
          onChange={(e) => player?.seek(Number(e.target.value))}
          style={{ "--pos": `${st.duration ? (100 * st.time) / st.duration : 0}%` } as React.CSSProperties}
        />
      </footer>
    </div>
  );
}

/** the live voice's head: the engine's own telemetry, with the body the voice panel sets */
function LiveHead(props: { name: string; words: SungWords | null; live: LiveShow }) {
  const { live, words } = props;
  const body = useStore((s) => s.body);
  const feedRef = useRef<HeadFeed | null>(null);
  const overlayRef = useRef<OverlayFn | undefined>(undefined);
  if (words && !overlayRef.current) overlayRef.current = mouthWords(() => (live.isPlaying ? wordAt(words, live.time()) : null), V.green, 1);
  if (!feedRef.current) {
    feedRef.current = {
      get model() {
        return getModel(useStore.getState().body, engine.sampleRate || 48000);
      },
      view: VIEW,
      maxDpr: 1.5,
      facing: 1,
      frame: () => {
        const st = useStore.getState();
        const lat = engine.latest;
        const tele = live.isPlaying && lat && sameBody(lat.body, st.body) ? lat : null;
        return { tele, artic: tele ? VoiceModel.articFromArray(tele.t.artic) : st.artic, epoch: live.epoch };
      },
    };
  }
  return (
    <Screen className="duet-head" focus title={props.name} sub={bodyLabel(body)} label={`${props.name} voice, ${bodyLabel(body)}, in 3D, sung live`}>
      <AnatomyView3D feed={feedRef.current} readouts={false} overlay={overlayRef.current} />
    </Screen>
  );
}

/** one voice's head; the last of several turns to face the others */
function Head(props: { name: string; track: TeleTrack; words: SungWords | null; show: ShowFile; transport: Transport; facing: 1 | -1; hair?: boolean }) {
  const { track, show, transport, words } = props;
  const feedRef = useRef<HeadFeed | null>(null);
  // the syllable at the mouth, written on the side the face looks to
  const overlayRef = useRef<OverlayFn | undefined>(undefined);
  if (words && !overlayRef.current) overlayRef.current = mouthWords(() => wordAt(words, transport.time()), V.green, props.facing);
  if (!feedRef.current) {
    const model = getModel(track.body, track.sampleRate);
    const beatStep = (t: number) => {
      if (!show.bpm) return -1;
      const s = Math.floor(((t - (show.downbeat ?? 0)) * show.bpm * 4) / 60);
      return s < 0 ? -1 : s % 16;
    };
    feedRef.current = {
      model,
      view: VIEW,
      maxDpr: 1.5,
      facing: props.facing,
      hair: props.hair,
      frame: () => {
        const t = transport.time();
        const i = track.indexAt(t);
        const msg = track.message(i, beatStep(t));
        // paused: the head keeps its shape, the voice and the face come to rest
        if (!transport.isPlaying) return { tele: null, artic: VoiceModel.articFromArray(msg.t.artic), epoch: transport.epoch };
        return { tele: msg, artic: VoiceModel.articFromArray(msg.t.artic), epoch: transport.epoch };
      },
    };
  }
  return (
    <Screen className="duet-head" focus title={props.name} sub={bodyLabel(track.body)} label={`${props.name} voice, ${bodyLabel(track.body)}, in 3D`}>
      <AnatomyView3D feed={feedRef.current} readouts={false} overlay={overlayRef.current} />
    </Screen>
  );
}
