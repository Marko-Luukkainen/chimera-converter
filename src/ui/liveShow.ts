/**
 * A show sung live: the voice's melody through the engine (so every voice setting is heard as it
 * changes), with the show's backing track, when it has one, on the engine's own audio context so
 * the two share one clock. Play, pause and seek work as the recorded show's transport does; the
 * time is the song's (the recording's clock, intro included).
 *
 * A seek, or a new body (the airway is rebuilt and the voice's clock starts again), restarts the
 * song at that moment: from the next phrase, since a phrase is planned with its own breath.
 */
import { engine } from "../audio/AudioEngine.ts";
import { useStore } from "./store.ts";
import { loadSong, playSong, stopSinging, useSing, type SongFile } from "./singing.ts";
import { sameBody, type BodyMix } from "./body.ts";
import { Transport } from "../show/transport.ts";

export class LiveShow {
  private backing: Transport | null = null;
  /** voice clock of song time 0 while it plays */
  private at: number | null = null;
  private pos = 0;
  private playing = false;
  private gen = 0;
  epoch = 0;
  /** the last thing that went wrong (shown by the page) */
  error: string | null = null;
  readonly songEnd: number;
  private readonly listeners = new Set<() => void>();
  /** the body the song was planned for, and its time a moment ago */
  private body: BodyMix | null = null;
  private lastT = 0;
  private readonly watch: ReturnType<typeof setInterval>;

  constructor(
    readonly melody: SongFile,
    private readonly backingData: ArrayBuffer | null,
    title: string,
  ) {
    const beat = 60 / melody.bpm;
    this.songEnd = (melody.t0 ?? 0.3) + melody.notes.reduce((s, n) => s + n[1], 0) * beat;
    const err = loadSong(melody, title);
    if (err) throw new Error(err);
    this.watch = setInterval(() => this.tick(), 150);
  }

  /** A new body stops the song (store.setBody) and starts the voice's clock again: once the engine
   * sings with it, sing on from where the song was. */
  private tick(): void {
    if (!this.playing || this.at === null) return;
    const lat = engine.latest;
    if (lat && this.body && !sameBody(lat.body, this.body)) {
      void this.restart(this.lastT);
      return;
    }
    this.lastT = this.time();
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  get duration(): number {
    return Math.max(this.songEnd + 0.5, this.backing?.duration ?? 0);
  }

  get hasBacking(): boolean {
    return !!this.backingData;
  }

  /** the band's level (the backing track; 1 as recorded) */
  set bandVolume(v: number) {
    this.band = v;
    if (this.backing) this.backing.volume = v;
  }
  private band = 0.8;

  subscribe(f: () => void): () => void {
    this.listeners.add(f);
    return () => this.listeners.delete(f);
  }

  private emit(): void {
    for (const f of this.listeners) f();
  }

  time(): number {
    if (!this.playing || this.at === null) return this.pos;
    const t = (engine.voiceClock() ?? 0) - this.at;
    if (t >= this.duration) {
      this.pos = this.duration;
      queueMicrotask(() => this.pause());
      return this.duration;
    }
    return Math.max(0, t);
  }

  /** Call from the tap: the audio starts on a user gesture. */
  async play(): Promise<void> {
    if (this.playing) return;
    if (this.pos >= this.duration - 0.05) this.pos = 0;
    await this.start(this.pos);
  }

  pause(): void {
    if (!this.playing) return;
    this.pos = this.time();
    this.stop();
    this.emit();
  }

  seek(t: number): void {
    t = Math.min(this.duration, Math.max(0, t));
    if (this.playing) void this.restart(t);
    else {
      this.pos = t;
      this.epoch++;
      this.emit();
    }
  }

  dispose(): void {
    clearInterval(this.watch);
    this.stop();
    this.backing?.dispose();
    this.backing = null;
    this.listeners.clear();
  }

  private stop(): void {
    this.gen++;
    this.playing = false;
    this.at = null;
    stopSinging();
    this.backing?.pause();
  }

  private async restart(t: number): Promise<void> {
    this.stop();
    this.pos = t;
    this.emit();
    await this.start(t);
  }

  private async start(from: number): Promise<void> {
    const gen = ++this.gen;
    this.playing = true;
    this.at = null;
    this.epoch++;
    this.error = null;
    this.emit();
    try {
      const st = useStore.getState();
      await st.start();
      if (useStore.getState().mode !== "sing") useStore.getState().setMode("sing");
      if (this.backingData && !this.backing && engine.ctx) {
        this.backing = new Transport(engine.ctx);
        this.backing.volume = this.band;
        await this.backing.load(this.backingData.slice(0));
      }
      // after a new body the voice's clock starts again: wait for the new voice to report
      const body = useStore.getState().body;
      for (let i = 0; i < 40 && !(engine.latest && sameBody(engine.latest.body, body)); i++) await new Promise((r) => setTimeout(r, 50));
      if (gen !== this.gen) return;
      this.body = body;
      this.lastT = from;
      const err = await playSong(body, undefined, {
        from,
        onStart: (at) => {
          if (gen !== this.gen) return;
          this.at = at;
          const b = this.backing;
          const ctx = engine.ctx;
          if (b && ctx) {
            // song time `from` sounds at voice clock at + from: the same moment on the context's clock
            const when = ctx.currentTime + (at + from - (engine.voiceClock() ?? 0));
            b.seek(from);
            b.play(when);
          }
        },
      });
      if (err && gen === this.gen) {
        this.error = err;
        this.stop();
      }
    } catch (e) {
      if (gen === this.gen) {
        this.error = e instanceof Error ? e.message : String(e);
        this.stop();
      }
    }
    this.emit();
  }
}

/** the melody a show's live voice sings: a song file with its title */
export type LiveMelody = SongFile;
export { useSing };
