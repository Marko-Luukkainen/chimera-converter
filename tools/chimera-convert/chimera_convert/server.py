"""The converter app's local server: upload a song, follow the conversion, edit the notes, hear
Chimera sing them, and hand the result to Chimera (a melody file or a duet-page show).

    python -m chimera_convert.server            # http://127.0.0.1:5320

Sessions live in tools/chimera-convert/out/sessions/<id>/ (outside git): the uploaded audio, the
lyrics, session.json (analysis, notes, state), the melody file and Chimera's render. One worker
thread runs the conversions, so the GPU does one song at a time.
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chimera, notes, pipeline, transcribe
from .langdetect import detect

ROOT = Path(__file__).resolve().parent.parent
SESSIONS = ROOT / "out" / "sessions"
ANALYSIS = "analysis.npz"
"""the slow part of a conversion, kept so the notes can be made again"""
DIST = ROOT / "app" / "dist"
FILES = {"original", "vocals.wav", "render.wav", "melody.json", "melody.csv", "lyrics.txt"}
CHIMERA_DEV_URL = "http://127.0.0.1:5317"


# ----------------------------------------------------------------------------- sessions

class Store:
    """session.json files, with a lock so the worker and requests don't write over each other."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def dir(self, sid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{6,40}", sid):
            raise HTTPException(404, "no such session")
        d = self.root / sid
        if not (d / "session.json").exists():
            raise HTTPException(404, "no such session")
        return d

    def load(self, sid: str) -> dict:
        with self.lock:
            return json.loads((self.dir(sid) / "session.json").read_text(encoding="utf-8"))

    def save(self, s: dict) -> None:
        with self.lock:
            d = self.root / s["id"]
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "session.json.tmp"
            tmp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
            # Windows refuses to replace a file someone has open for a moment (a reader): retry
            for attempt in range(40):
                try:
                    tmp.replace(d / "session.json")
                    break
                except PermissionError:
                    if attempt == 39:
                        raise
                    time.sleep(0.05)

    def update(self, sid: str, **kw) -> dict:
        with self.lock:
            s = self.load(sid)
            s.update(kw)
            self.save(s)
            return s

    def all(self) -> list[dict]:
        out = []
        for p in sorted(self.root.glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        return out


def summary(s: dict) -> dict:
    return {k: s.get(k) for k in ("id", "title", "created", "status", "stage", "progress", "error", "lang", "duration")}


def notes_from(s: dict) -> list[notes.Note]:
    return [notes.Note(n["start"], n["end"], n["midi"], n["syl"]) for n in s["notes"]]


# ----------------------------------------------------------------------------- the worker

STAGES = {"loading": (0.02, "Loading the audio"), "separating the voice": (0.05, "Separating the voice"),
          "pitch": (0.45, "Tracking the pitch"), "aligning the lyrics": (0.65, "Aligning the lyrics"),
          "notes": (0.9, "Making the notes")}


class Worker:
    def __init__(self, store: Store, repo: Path | None):
        self.store = store
        self.repo = repo
        self.cli = chimera.find_cli(repo)
        self.device = pipeline.pick_device("auto")
        self.q: queue.Queue[str] = queue.Queue()
        self.pending: set[str] = set()
        """sessions in the queue, not yet started"""
        self.lock = threading.Lock()
        threading.Thread(target=self.run, daemon=True).start()

    def submit(self, sid: str) -> None:
        with self.lock:
            if sid in self.pending:
                return
            self.pending.add(sid)
        self.q.put(sid)

    def adopt(self, sessions: list[dict]) -> None:
        """Queue sessions marked queued that no one sent here (marked by hand, or by another
        server process): otherwise they would wait forever."""
        for s in sessions:
            if s.get("status") == "queued" and s["id"] not in self.pending:
                self.submit(s["id"])

    def run(self) -> None:
        while True:
            sid = self.q.get()
            with self.lock:
                self.pending.discard(sid)
            try:
                self.convert(sid)
            except Exception as e:  # noqa: BLE001 - shown to the user, kept in the log
                traceback.print_exc()
                self.store.update(sid, status="error", error=str(e) or e.__class__.__name__, stage="Error")

    def convert(self, sid: str) -> None:
        """Two phases: the analysis (separation, pitch, the alignment model: slow, cached in
        analysis.npz), then the notes from it with the chosen thresholds of what counts as singing
        (fast). Unless the song was added without it, the conversion stops between the two for the
        user to check the thresholds ("review")."""
        d = self.store.dir(sid)
        s = self.store.update(sid, status="running", stage="Preparing", progress=0.0, error=None)
        opt = s["options"]

        def progress(stage: str, frac: float) -> None:
            p, label = STAGES.get(stage, (s.get("progress", 0), stage))
            self.store.update(sid, stage=label, progress=p)

        cache = d / ANALYSIS
        vocals = d / "vocals.wav"
        if s.get("phase", "analyze") == "analyze" or not cache.exists():
            if opt["separate"] and not vocals.exists():
                an = pipeline.analyze_audio(d / s["files"]["original"], True, self.device, None, vocals, progress)
            else:
                src = vocals if vocals.exists() else d / s["files"]["original"]
                an = pipeline.analyze_audio(src, False, self.device, None, None, progress, voice_only=vocals.exists())
            if opt.get("align", "mms") == "mms":
                from . import align

                progress("aligning the lyrics", 0.0)
                an.em = align.emissions(an.y16, align.DEFAULT_MODEL, self.device)
            pipeline.save_analysis(cache, an)
            sug = an.singing.to_dict()
            s = self.store.load(sid)
            s.update(singing=sug, singing_suggested=sug, phase="notes", duration=round(an.duration, 3), pitch_method=an.pitch_method)
            if vocals.exists():
                s["files"]["vocals"] = "vocals.wav"
            self.store.save(s)
            if opt.get("review", True):
                self.store.update(sid, status="review", stage="Check what counts as singing", progress=1.0)
                return
        else:
            an = pipeline.load_analysis(cache, transcribe.Detection.from_dict(s.get("singing")))
        self.make_notes(sid, an, progress)

    def make_notes(self, sid: str, an: pipeline.Analysis, progress) -> None:
        d = self.store.dir(sid)
        s = self.store.load(sid)
        progress("notes", 0.0)
        text = (d / "lyrics.txt").read_text(encoding="utf-8")
        lyr = pipeline.prepare_lyrics(text, s["lang"], self.cli, self.repo)
        o = notes.Opts()
        pl = pipeline.place_notes(lyr, an, s["options"].get("align", "mms"), self.device, o, None, progress, log=lambda *_: None)
        ns = pl.notes
        mel = pipeline.build_melody(ns, lyr, source=s["files"]["original"], cli=self.cli)
        midi = [None if not np.isfinite(v) else round(float(v), 2) for v in an.midi]
        s = self.store.load(sid)
        s.update(status="done", stage="Done", progress=1.0, lyrics=lyr.to_dict(), phase="notes",
                 syllables=lyr.syl_text, syl_word=lyr.syl_word,
                 contour={"hop": float(an.t[1] - an.t[0]) if len(an.t) > 1 else 0.01, "midi": midi},
                 duration=round(an.duration, 3), pitch_method=an.pitch_method,
                 notes=[asdict(n) for n in ns], auto_notes=[asdict(n) for n in ns],
                 body=mel.data["body"], transpose=0.0, vibrato=35.0,
                 melody=mel.data, warnings=mel.warnings, render=None, doubtful=pl.doubtful,
                 singing=an.singing.to_dict() if an.singing else s.get("singing"),
                 tuning_cents=round(float(np.median(an.tr.tuning)) * 100) if an.tr else 0)
        self.store.save(s)
        write_melody(d, mel.data, ns, lyr.syl_text)


def write_melody(d: Path, data: dict, ns: list[notes.Note], syl_text: list[str]) -> None:
    chimera.write_json(d / "melody.json", data)
    chimera.write_csv(d / "melody.csv", ns, syl_text, 0.0)


# ----------------------------------------------------------------------------- Chimera singing

def melody_seconds(mel: dict) -> float:
    beat = 60.0 / float(mel.get("bpm", 60))
    return float(mel.get("t0", 0.3)) + sum(float(n[1]) for n in mel.get("notes", [])) * beat


class Renders:
    """`chimera render notes` in the background, one per song, with its progress. The CLI says
    nothing until it is done, so the progress is an estimate: the song's length times how long a
    second of song took to sing last time on this machine (kept in the sessions folder)."""

    SPEED = "render_speed.json"
    DEFAULT_SPEED = 1.0
    """seconds of rendering per second of song, before the first render has measured it"""

    def __init__(self, store: Store):
        self.store = store
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def speed(self) -> float:
        try:
            v = float(json.loads((self.store.root / self.SPEED).read_text(encoding="utf-8"))["seconds_per_second"])
            return v if 0.01 < v < 100 else self.DEFAULT_SPEED
        except (OSError, ValueError, KeyError, TypeError):
            return self.DEFAULT_SPEED

    def learn(self, seconds_per_second: float) -> None:
        old = self.speed()
        new = seconds_per_second if not (self.store.root / self.SPEED).exists() else 0.5 * old + 0.5 * seconds_per_second
        try:
            (self.store.root / self.SPEED).write_text(json.dumps({"seconds_per_second": round(new, 4)}), encoding="utf-8")
        except OSError:
            pass

    def start(self, sid: str, s: dict, voice: str, cli) -> dict | None:
        with self.lock:
            j = self.jobs.get(sid)
            if j and j["state"] == "running":
                return None
            length = melody_seconds(s["melody"])
            j = {"state": "running", "started": time.time(), "length": length, "expected": max(1.0, length * self.speed()),
                 "body": voice, "error": None, "render": None, "url": None}
            self.jobs[sid] = j
        threading.Thread(target=self._run, args=(sid, s, voice, cli, j), daemon=True).start()
        return j

    def _run(self, sid: str, s: dict, voice: str, cli, j: dict) -> None:
        d = self.store.dir(sid)
        cmd, cwd = cli
        try:
            p = subprocess.run(cmd + ["render", "notes", str(d / "melody.json"), str(d / "render"), voice, "--tele", str(d / "voice.tele")],
                               cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if p.returncode != 0:
                raise RuntimeError(f"chimera render failed: {p.stderr.strip()[-400:]}")
            took = time.time() - j["started"]
            if j["length"] > 1.0:
                self.learn(took / j["length"])
            render = {"body": voice, "melody": s["melody"], "time": time.time(), "offset": s["melody"].get("offset", 0.0)}
            self.store.update(sid, render=render)
            j.update(state="done", render=render, url=f"/api/sessions/{sid}/file/render.wav?t={int(render['time'])}")
        except Exception as e:  # noqa: BLE001 - shown to the user
            traceback.print_exc()
            j.update(state="error", error=str(e) or e.__class__.__name__)

    def status(self, sid: str) -> dict:
        j = self.jobs.get(sid)
        if not j:
            return {"state": "idle"}
        elapsed = time.time() - j["started"]
        if j["state"] == "running":
            # the estimate eases toward 99 % rather than stopping at 100 % when it runs long
            x = elapsed / j["expected"]
            progress = 0.95 * x if x < 1 else 0.95 + 0.04 * (1 - 1 / (1 + 2 * (x - 1)))
        else:
            progress = 1.0 if j["state"] == "done" else 0.0
        return {"state": j["state"], "progress": round(progress, 3), "elapsed": round(elapsed, 1), "expected": round(j["expected"], 1),
                "length": round(j["length"], 1), "error": j["error"], "render": j["render"], "url": j["url"]}


# ----------------------------------------------------------------------------- the app

class NotesIn(BaseModel):
    notes: list[dict]
    body: str | None = None
    transpose: float = 0.0
    vibrato: float = 35.0


class RenderIn(BaseModel):
    body: str | None = None


class ShowIn(BaseModel):
    show_id: str
    mix: str = "chimera"
    """chimera: Chimera alone; original: the recording; both: the two together"""
    title: str | None = None


class LangIn(BaseModel):
    lang: str


class SingingIn(BaseModel):
    gate_db: float = -38.0
    clarity: float = 0.15
    rough: float = 0.0
    hold: float = 0.4


class ReviewIn(BaseModel):
    back: bool = False


class DetectIn(BaseModel):
    lyrics: str


def create_app(repo: Path | None = None, sessions: Path = SESSIONS, start_worker: bool = True) -> FastAPI:
    repo = repo or chimera.default_repo()
    store = Store(sessions)
    worker = Worker(store, repo) if start_worker else None
    # conversions cut off by a restart start again
    if worker:
        for s0 in store.all():
            if s0.get("status") in ("queued", "running"):
                store.update(s0["id"], status="queued", stage="Queued", progress=0.0)
                worker.submit(s0["id"])
    app = FastAPI(title="chimera-convert")
    # Chimera's own page (its dev server) reads melody files from here to sing them live
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5317", "http://localhost:5317"], allow_methods=["GET"], allow_headers=["*"])
    app.state.store, app.state.worker = store, worker
    renders = Renders(store)

    def lyrics_of(s: dict) -> pipeline.Lyrics:
        return pipeline.Lyrics.from_dict(s["lyrics"])

    @app.get("/api/info")
    def info():
        gpu = None
        try:
            import torch

            gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        except Exception:  # noqa: BLE001
            pass
        cli = chimera.find_cli(repo)
        return {"repo": str(repo) if repo else None, "chimera_cli": bool(cli), "gpu": gpu,
                "shows": str(repo / "public" / "shows") if repo else None, "chimera_url": CHIMERA_DEV_URL}

    @app.post("/api/detect")
    def detect_lang(body: DetectIn):
        return detect(body.lyrics).to_dict()

    @app.get("/api/sessions")
    def sessions_list():
        ss = store.all()
        if worker:
            worker.adopt(ss)
        return [summary(s) for s in ss]

    @app.post("/api/sessions")
    async def sessions_new(audio: UploadFile = File(...), lyrics: str = Form(...), lang: str = Form("auto"),
                           separate: bool = Form(False), title: str = Form(""), align: str = Form("mms"),
                           review: bool = Form(True)):
        if lang not in ("auto", "fi", "en"):
            raise HTTPException(400, "lang must be auto, fi or en")
        try:
            lang_used, det = pipeline.resolve_lang(lyrics, lang)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"detail": e.args[0], "detection": e.args[1], "need": "lang"})
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        d = sessions / sid
        d.mkdir(parents=True)
        ext = Path(audio.filename or "audio.wav").suffix.lower() or ".wav"
        if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
            ext = ".wav"
        with open(d / f"original{ext}", "wb") as f:
            shutil.copyfileobj(audio.file, f)
        (d / "lyrics.txt").write_text(lyrics, encoding="utf-8")
        s = {"id": sid, "title": title or Path(audio.filename or "laulu").stem, "created": time.time(),
             "status": "queued", "stage": "Queued", "progress": 0.0, "error": None,
             "lang": lang_used, "lang_requested": lang, "detection": det,
             "options": {"separate": separate, "align": align, "review": review}, "files": {"original": f"original{ext}"},
             "phase": "analyze",
             "lyrics_text": lyrics}
        store.save(s)
        worker.submit(sid)
        return summary(s)

    @app.get("/api/sessions/{sid}")
    def session_get(sid: str):
        s = store.load(sid)
        if worker:
            worker.adopt([s])
        return s

    @app.post("/api/sessions/{sid}/lang")
    def session_lang(sid: str, body: LangIn):
        """Sing the lyrics in another language: new syllables, so the notes are placed again
        (the analysed voice is kept: a separated stem is reused)."""
        if body.lang not in ("fi", "en"):
            raise HTTPException(400, "lang must be fi or en")
        s = store.update(sid, lang=body.lang, status="queued", stage="Queued", progress=0.0, render=None, phase="notes")
        worker.submit(sid)
        return summary(s)

    @app.get("/api/sessions/{sid}/singing")
    def session_singing(sid: str):
        """What the thresholds work on, for the app to draw and to try them on before the notes are
        made: the level (dB below the loudest moment) and the pitch clarity every 20 ms."""
        s = store.load(sid)
        cache = store.dir(sid) / ANALYSIS
        if not cache.exists():
            raise HTTPException(409, "not analysed yet")
        a = np.load(cache)
        db = transcribe.level_db(a["rms"])
        per = np.where(a["hz"] > 0, a["per"], 0.0)
        n = min(len(db), len(per)) // 2 * 2
        db2 = db[:n].reshape(-1, 2).max(1)
        per2 = per[:n].reshape(-1, 2).max(1)
        return {"hop": 2 * transcribe.HOP, "db": [round(float(x), 1) for x in np.maximum(db2, -90)],
                "clarity": [round(float(x), 2) for x in per2], "voice_only": bool(a["voice_only"]),
                "current": s.get("singing") or s.get("singing_suggested"), "suggested": s.get("singing_suggested"),
                "syllables": len(s["syllables"]) if s.get("syllables") else None, "duration": float(a["duration"]),
                "audio": "vocals.wav" if (store.dir(sid) / "vocals.wav").exists() else "original", "has_notes": bool(s.get("notes"))}

    @app.post("/api/sessions/{sid}/singing")
    def session_singing_set(sid: str, body: SingingIn):
        """Make the notes with these thresholds."""
        s = store.load(sid)
        if not (store.dir(sid) / ANALYSIS).exists():
            raise HTTPException(409, "not analysed yet")
        if s.get("status") in ("queued", "running"):
            raise HTTPException(409, "already converting")
        det = transcribe.Detection.from_dict(body.model_dump())
        s = store.update(sid, singing=det.to_dict(), status="queued", stage="Queued", progress=0.0, phase="notes", render=None)
        worker.submit(sid)
        return summary(s)

    @app.post("/api/sessions/{sid}/review")
    def session_review(sid: str, body: ReviewIn):
        """Back to the thresholds (the notes stay until new ones are made), or, `back`, from them to
        the notes as they were."""
        s = store.load(sid)
        if s.get("status") in ("queued", "running"):
            raise HTTPException(409, "already converting")
        if body.back:
            if not s.get("notes"):
                raise HTTPException(409, "no notes yet")
            return summary(store.update(sid, status="done", stage="Done", progress=1.0))
        if not (store.dir(sid) / ANALYSIS).exists():
            # a song converted before the analysis was kept: analyse it again, then stop here
            s["options"]["review"] = True
            s.update(status="queued", stage="Queued", progress=0.0, phase="analyze")
            store.save(s)
            worker.submit(sid)
            return summary(s)
        return summary(store.update(sid, status="review", stage="Check what counts as singing", progress=1.0))

    @app.put("/api/sessions/{sid}/notes")
    def session_notes(sid: str, body: NotesIn):
        s = store.load(sid)
        if s.get("status") != "done":
            raise HTTPException(409, "the conversion isn't finished")
        lyr = lyrics_of(s)
        try:
            ns = [notes.Note(float(n["start"]), float(n["end"]), float(n["midi"]), None if n.get("syl") is None else int(n["syl"]))
                  for n in body.notes]
            ns.sort(key=lambda n: n.start)
            if lyr.lang != "fi":
                ns = chimera.merge_inner_melismas(ns, lyr.syl_word, lyr.words, log=lambda *_: None)
            mel = pipeline.build_melody(ns, lyr, transpose=body.transpose, vibrato=body.vibrato,
                                        source=s["files"]["original"], body=body.body or s.get("body"), cli=worker.cli if worker else None)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e))
        s.update(notes=[asdict(n) for n in ns], melody=mel.data, warnings=mel.warnings, body=mel.data["body"],
                 transpose=body.transpose, vibrato=body.vibrato)
        store.save(s)
        write_melody(store.dir(sid), mel.data, ns, lyr.syl_text)
        return {"notes": s["notes"], "melody": mel.data, "warnings": mel.warnings}

    @app.post("/api/sessions/{sid}/render")
    def session_render(sid: str, body: RenderIn):
        """Start Chimera singing the current notes (in the background: a long song takes a while);
        GET .../render follows it."""
        s = store.load(sid)
        cli = chimera.find_cli(repo)
        if not cli:
            raise HTTPException(503, "Chimera CLI not found (build it: cargo build --release -p chimera-cli)")
        if not s.get("melody"):
            raise HTTPException(409, "no melody yet")
        voice = body.body or s.get("body") or "female"
        job = renders.start(sid, s, voice, cli)
        if job is None:
            raise HTTPException(409, "Chimera is already singing this song")
        return renders.status(sid)

    @app.get("/api/sessions/{sid}/render")
    def session_render_status(sid: str):
        store.load(sid)  # 404 for an unknown song
        return renders.status(sid)

    @app.post("/api/sessions/{sid}/show")
    def session_show(sid: str, body: ShowIn):
        """A show for Chimera's duet page (?show=<id>): the mix, the voice's telemetry and its
        melody, in public/shows/<id>/ (gitignored there)."""
        s = store.load(sid)
        if not repo:
            raise HTTPException(503, "Chimera checkout not found")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", body.show_id):
            raise HTTPException(400, "show id: lowercase letters, digits, - and _")
        r = s.get("render")
        if not r or r.get("melody") != s.get("melody"):
            raise HTTPException(409, "render the current notes first")
        d = store.dir(sid)
        out = repo / "public" / "shows" / body.show_id
        out.mkdir(parents=True, exist_ok=True)
        mix_audio(d, s, body.mix, out / "mix.wav")
        shutil.copyfile(d / "voice.tele", out / "voice.tele")
        # the melody: the words at the mouth, and what the page sings live
        shutil.copyfile(d / "melody.json", out / "melody.json")
        voice = {"name": "Chimera", "tele": "voice.tele", "melody": "melody.json"}
        show = {"title": body.title or s["title"], "audio": "mix.wav", "voices": [voice]}
        if write_backing(d, s, out / "backing.wav"):
            show["backing"] = "backing.wav"
        (out / "show.json").write_text(json.dumps(show, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"dir": str(out), "url": f"{CHIMERA_DEV_URL}/?show={body.show_id}", "words": True, "backing": "backing" in show}

    @app.post("/api/sessions/{sid}/live")
    def session_live(sid: str):
        """The melody where Chimera's own page can read it (public/shows is gitignored there), and
        the link that opens it in Sing mode: same origin, so no browser blocks the read."""
        s = store.load(sid)
        if not repo:
            raise HTTPException(503, "Chimera checkout not found")
        if not s.get("melody"):
            raise HTTPException(409, "no melody yet")
        out = repo / "public" / "shows" / "_live"
        out.mkdir(parents=True, exist_ok=True)
        data = dict(s["melody"], title=s["title"])
        (out / f"{sid}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        from urllib.parse import quote

        return {"url": f"{CHIMERA_DEV_URL}/?melody={quote(f'/shows/_live/{sid}.json?t={int(time.time())}', safe='')}&title={quote(s['title'])}"}

    @app.get("/api/sessions/{sid}/file/{name}")
    def session_file(sid: str, name: str):
        s = store.load(sid)
        d = store.dir(sid)
        if name not in FILES:
            raise HTTPException(404)
        path = d / (s["files"]["original"] if name == "original" else name)
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="app")
    return app


def mix_audio(d: Path, s: dict, mix: str, out: Path, sr: int = 48000) -> None:
    """The show's track. The render's clock runs `offset` later than the recording's (the melody
    starts no earlier than 0.3 s), so the recording is delayed by that much to stay in sync."""
    import librosa
    import soundfile as sf

    render, _ = sf.read(str(d / "render.wav"), dtype="float32", always_2d=False)
    if render.ndim > 1:
        render = render.mean(1)
    if mix == "chimera":
        y = render
    else:
        orig, _ = librosa.load(str(d / s["files"]["original"]), sr=sr, mono=True)
        off = int(round(float(s.get("melody", {}).get("offset", 0.0)) * sr))
        orig = np.concatenate([np.zeros(off, np.float32), orig])
        if mix == "original":
            y = orig
        else:
            n = max(len(orig), len(render))
            y = np.zeros(n, np.float32)
            y[:len(orig)] += 0.6 * orig
            y[:len(render)] += 0.9 * render
    peak = float(np.abs(y).max()) if len(y) else 0.0
    if peak > 0.99:
        y = y * (0.99 / peak)
    sf.write(str(out), y, sr, subtype="PCM_16")


def write_backing(d: Path, s: dict, out: Path, sr: int = 48000) -> bool:
    """The recording without its voice (the recording less the separated voice), on the melody's
    clock (delayed by its `offset`, as the mix is): what the duet page's live voice sings over.
    False when the voice was never separated (the recording is a voice alone, or a mix the
    converter didn't split)."""
    vocals = d / "vocals.wav"
    if not vocals.exists():
        return False
    import librosa
    import soundfile as sf

    orig, _ = librosa.load(str(d / s["files"]["original"]), sr=sr, mono=True)
    voc, _ = librosa.load(str(vocals), sr=sr, mono=True)
    n = min(len(orig), len(voc))
    y = orig.copy()
    y[:n] -= voc[:n]
    off = int(round(float(s.get("melody", {}).get("offset", 0.0)) * sr))
    y = np.concatenate([np.zeros(off, np.float32), y.astype(np.float32)])
    peak = float(np.abs(y).max()) if len(y) else 0.0
    if peak > 0.99:
        y = y * (0.99 / peak)
    sf.write(str(out), y, sr, subtype="PCM_16")
    return True


def main() -> None:
    import argparse
    import webbrowser

    import uvicorn

    ap = argparse.ArgumentParser(prog="chimera_convert.server")
    ap.add_argument("--port", type=int, default=5320)
    ap.add_argument("--chimera", type=Path, default=None)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    app = create_app(a.chimera)
    url = f"http://127.0.0.1:{a.port}"
    print(f"chimera-convert: {url}")
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
