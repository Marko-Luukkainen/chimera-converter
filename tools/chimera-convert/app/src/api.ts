import type { Note } from "./edit.ts";

export type Lang = "fi" | "en";
export type Style = "sing" | "rap" | "speech";

/** the rap style's settings (server: rap.Opts): seconds, dB per 20 ms, a fraction */
export interface RapSettings {
  rest: number;
  window: number;
  min_rise: number;
  nucleus: number;
  keep_cents: boolean;
}

/** the speech style's settings (server: speech.Opts) */
export interface SpeechSettings {
  rest: number;
  window: number;
  min_rise: number;
  nucleus: number;
  /** "voice": the intonation at the chosen voice's range; "speaker": at the speaker's own pitch */
  pitch: "voice" | "speaker";
  /** pitch intervals scaled (1 = as spoken) */
  expression: number;
  /** loudness differences scaled (1 = as spoken) */
  dynamics: number;
}

export interface Detection {
  lang: Lang | null;
  guess: "fi" | "en" | "other";
  confidence: number;
  reason: string;
  words: number;
}

export interface Melody {
  bpm: number;
  lyrics: string;
  t0: number;
  vibrato: number;
  lang: Lang;
  body: string;
  offset?: number;
  notes?: [number, number][];
  /** a speech file (the speech style): said by Chimera's speech planner, not sung */
  kind?: "spoken";
}

export interface Session {
  id: string;
  title: string;
  created: number;
  status: "queued" | "running" | "review" | "done" | "error";
  stage: string;
  progress: number;
  error: string | null;
  lang: Lang;
  lang_requested: "auto" | Lang;
  detection: Detection;
  options: {
    separate: boolean;
    align: string;
    review?: boolean;
    style?: Style;
    rap?: RapSettings;
    speech?: SpeechSettings;
    separator?: string | null;
    lead_only?: boolean;
  };
  /** what counted as singing (the thresholds the notes were made with) */
  singing?: Singing;
  files: { original: string; vocals?: string };
  lyrics_text: string;
  lyrics?: { words: { text: string; syls: { text: string }[]; phrase_end: boolean }[] };
  syllables?: string[];
  syl_word?: [number, number][];
  contour?: { hop: number; midi: (number | null)[] };
  duration?: number;
  notes?: Note[];
  auto_notes?: Note[];
  body?: string;
  transpose?: number;
  vibrato?: number;
  melody?: Melody;
  warnings?: string[];
  /** syllables that found no singing to sit on */
  doubtful?: number[];
  tuning_cents?: number;
  render?: { body: string; melody: Melody; time: number; offset: number } | null;
}

/** what counts as singing: louder than `gate_db` (dB below the loudest moment) and a pitch
 * clearer than `clarity`, or (`rough`) loud enough alone; gaps shorter than `hold` s are held */
export interface Singing {
  gate_db: number;
  clarity: number;
  rough: number;
  hold: number;
}

/** what the thresholds work on: level and pitch clarity every `hop` s */
export interface SingingData {
  hop: number;
  db: number[];
  clarity: number[];
  voice_only: boolean;
  current: Singing;
  suggested: Singing;
  syllables: number | null;
  duration: number;
  audio: string;
  has_notes: boolean;
}

export type Summary = Pick<Session, "id" | "title" | "created" | "status" | "stage" | "progress" | "error" | "lang" | "duration">;

export interface Info {
  repo: string | null;
  chimera_cli: boolean;
  gpu: string | null;
  shows: string | null;
  chimera_url: string;
  separators?: Record<string, boolean>;
  rap_defaults?: RapSettings;
  speech_defaults?: SpeechSettings;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly body: any) {
    super(message);
  }
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch(url, init);
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) {
    const detail = data?.detail;
    throw new ApiError(typeof detail === "string" ? detail : `${r.status} ${r.statusText}`, r.status, data);
  }
  return data as T;
}

export const api = {
  info: () => call<Info>("GET", "/api/info"),
  detect: (lyrics: string) => call<Detection>("POST", "/api/detect", { lyrics }),
  sessions: () => call<Summary[]>("GET", "/api/sessions"),
  session: (id: string) => call<Session>("GET", `/api/sessions/${id}`),
  create: (form: FormData) => call<Summary>("POST", "/api/sessions", form),
  /** create with upload progress (0..1) */
  upload: (form: FormData, onProgress: (f: number) => void) =>
    new Promise<Summary>((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", "/api/sessions");
      x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      x.onload = () => {
        let data: any = null;
        try {
          data = JSON.parse(x.responseText);
        } catch {}
        if (x.status >= 200 && x.status < 300) resolve(data);
        else reject(new ApiError(typeof data?.detail === "string" ? data.detail : `${x.status} ${x.statusText}`, x.status, data));
      };
      x.onerror = () => reject(new ApiError("Can't reach the converter server. Is start_app.bat running?", 0, null));
      x.send(form);
    }),
  setLang: (id: string, lang: Lang) => call<Summary>("POST", `/api/sessions/${id}/lang`, { lang }),
  /** sing it as rap or singing (or with other rap settings): the notes again from the kept analysis */
  setStyle: (id: string, style: Style, rap?: RapSettings, speech?: SpeechSettings) =>
    call<Summary>("POST", `/api/sessions/${id}/style`, { style, rap, speech }),
  singing: (id: string) => call<SingingData>("GET", `/api/sessions/${id}/singing`),
  setSinging: (id: string, v: Singing) => call<Summary>("POST", `/api/sessions/${id}/singing`, v),
  review: (id: string, back = false) => call<Summary>("POST", `/api/sessions/${id}/review`, { back }),
  saveNotes: (id: string, body: { notes: Note[]; body?: string; transpose: number; vibrato: number }) =>
    call<{ notes: Note[]; melody: Melody; warnings: string[] }>("PUT", `/api/sessions/${id}/notes`, body),
  render: (id: string, body?: string) => call<RenderJob>("POST", `/api/sessions/${id}/render`, { body }),
  renderStatus: (id: string) => call<RenderJob>("GET", `/api/sessions/${id}/render`),
  show: (id: string, show_id: string, mix: string, title?: string) =>
    call<{ dir: string; url: string; words: boolean }>("POST", `/api/sessions/${id}/show`, { show_id, mix, title }),
  live: (id: string) => call<{ url: string }>("POST", `/api/sessions/${id}/live`),
  file: (id: string, name: string) => `/api/sessions/${id}/file/${name}`,
};

/** Chimera singing a song in the background; `progress` is the server's estimate (the CLI is
 * silent until it is done), `elapsed` and `expected` are seconds */
export interface RenderJob {
  state: "idle" | "running" | "done" | "error";
  progress?: number;
  elapsed?: number;
  expected?: number;
  length?: number;
  error?: string | null;
  render?: Session["render"];
  url?: string | null;
}

export const LANG_NAMES: Record<string, string> = { fi: "Finnish", en: "English", other: "another language" };
