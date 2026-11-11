"""The app's server end to end on a synthetic song, with a stand-in Chimera CLI."""

import gzip
import json
import sys
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from chimera_convert.server import create_app
from test_notes import SR, voice

FAKE_CLI = r'''#!{py}
import json, sys, wave, struct, math
a = sys.argv[1:]
if a[:2] != ["render", "notes"]:
    sys.exit(2)
m = json.load(open(a[2], encoding="utf-8"))
if len(m["notes"]) == 1:
    sys.exit(1)  # the syllable probe: no list, so the converter skips the check
n = 48000 * 2
with wave.open(a[3] + ".wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(n)))
if "--tele" in a:
    open(a[a.index("--tele") + 1], "wb").write(b"TELE")
print(a[3] + ".wav: 2.00 s, peak 0.250, {{}} notes".format(len(m["notes"])))
'''


@pytest.fixture()
def client(tmp_path, monkeypatch):
    repo = tmp_path / "chimera"
    script = tmp_path / "fake_chimera.py"
    (repo / "target" / "release").mkdir(parents=True)
    (repo / "Cargo.toml").write_text("")
    script.write_text(FAKE_CLI.format(py=sys.executable), encoding="utf-8")
    # run through Python, so the stand-in works on Windows too
    monkeypatch.setattr("chimera_convert.chimera.find_cli", lambda r: ([sys.executable, str(script)], r) if r else None)
    (repo / "public" / "data").mkdir(parents=True)
    with gzip.open(repo / "public" / "data" / "cmudict.txt.gz", "wt", encoding="utf-8") as f:
        f.write("pieni\tP IY1 N IY0\nhti\tH T IY1\ntuikkii\tT UW1 K IY0\nt\tT IY1\ny\tW AY1\n")
    app = create_app(repo, tmp_path / "sessions")
    with TestClient(app) as c:
        c.repo = repo
        c.sessions = tmp_path / "sessions"
        yield c


def wait_done(c, sid, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        s = c.get(f"/api/sessions/{sid}").json()
        if s["status"] in ("done", "error", "review"):
            return s
        time.sleep(0.2)
    raise TimeoutError(s)


def wait_rendered(c, sid, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/sessions/{sid}/render").json()
        if j["state"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise TimeoutError(j)


def upload(c, tmp_path, lyrics, lang="auto", review=False):
    wav = tmp_path / "laulu.wav"
    sf.write(wav, voice(), SR)
    with open(wav, "rb") as f:
        return c.post("/api/sessions", files={"audio": ("laulu.wav", f, "audio/wav")},
                      data={"lyrics": lyrics, "lang": lang, "align": "none", "title": "Testi", "review": str(review).lower()})


def test_unclear_language_is_asked_before_anything_runs(client, tmp_path):
    r = upload(client, tmp_path, "La la la")
    assert r.status_code == 422 and r.json()["need"] == "lang"
    assert client.get("/api/sessions").json() == []
    assert client.post("/api/detect", json={"lyrics": "Pieni tähti tuikkii taivaalla"}).json()["lang"] == "fi"


def test_convert_edit_render_and_show(client, tmp_path):
    r = upload(client, tmp_path, "Pieni tähti,\ntuikkii yö")
    assert r.status_code == 200, r.text
    s = wait_done(client, r.json()["id"])
    assert s["status"] == "done", s.get("error")
    assert s["lang"] == "fi" and s["detection"]["lang"] == "fi"
    assert [round(n["midi"]) for n in s["notes"]] == [60, 62, 64, 62, 67, 65, 64]
    assert s["melody"]["lyrics"] == "Pie-ni täh-ti,\ntuik-kii yö"
    assert len(s["contour"]["midi"]) > 400

    # edit: raise the last note a tone; a broken edit (two notes on one syllable head) is refused
    ns = s["notes"]
    ns[-1]["midi"] = 66
    r = client.put(f"/api/sessions/{s['id']}/notes", json={"notes": ns, "body": "male", "transpose": -12})
    assert r.status_code == 200, r.text
    assert r.json()["melody"]["notes"][-1][0] == 54 and r.json()["melody"]["body"] == "male"
    bad = [dict(n) for n in ns]
    bad[1]["syl"] = 0
    assert client.put(f"/api/sessions/{s['id']}/notes", json={"notes": bad}).status_code == 400

    # a show needs a render of the current notes
    assert client.post(f"/api/sessions/{s['id']}/show", json={"show_id": "testi"}).status_code == 409
    r = client.post(f"/api/sessions/{s['id']}/render", json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "running" and 0 <= r.json()["progress"] < 1
    j = wait_rendered(client, s["id"])
    assert j["state"] == "done" and j["progress"] == 1.0, j
    assert client.get(j["url"]).status_code == 200
    # the time it took is kept, so the next estimate fits this machine
    assert (client.sessions / "render_speed.json").exists()
    r = client.post(f"/api/sessions/{s['id']}/show", json={"show_id": "testi", "mix": "both"})
    assert r.status_code == 200, r.text
    show_dir = client.repo / "public" / "shows" / "testi"
    show = json.loads((show_dir / "show.json").read_text(encoding="utf-8"))
    assert show["audio"] == "mix.wav" and show["voices"][0]["tele"] == "voice.tele"
    # the melody (Finnish words at the mouth, and the live voice); no backing: the voice wasn't separated
    assert show["voices"][0]["melody"] == "melody.json" and (show_dir / "melody.json").exists()
    assert "backing" not in show
    y, sr = sf.read(show_dir / "mix.wav")
    assert sr == 48000 and len(y) >= 4.5 * 48000  # the recording is in the mix

    # live in Chimera: the melody lands in Chimera's public/shows/_live, linked same-origin
    r = client.post(f"/api/sessions/{s['id']}/live")
    assert r.status_code == 200 and "/?melody=%2Fshows%2F_live%2F" in r.json()["url"]
    live = json.loads((client.repo / "public" / "shows" / "_live" / f"{s['id']}.json").read_text(encoding="utf-8"))
    assert live["lang"] == "fi" and live["notes"] and live["title"] == "Testi"

    # another language for the same recording: placed again
    r = client.post(f"/api/sessions/{s['id']}/lang", json={"lang": "en"})
    assert r.status_code == 200
    s2 = wait_done(client, s["id"])
    assert s2["status"] == "done", s2.get("error")
    assert s2["lang"] == "en" and s2["render"] is None
    assert "-" not in s2["melody"]["lyrics"].replace(" - ", " ")  # English words aren't hyphenated


def test_files_are_whitelisted(client, tmp_path):
    sid = upload(client, tmp_path, "Pieni tähti,\ntuikkii yö").json()["id"]
    wait_done(client, sid)
    assert client.get(f"/api/sessions/{sid}/file/original").status_code == 200
    assert client.get(f"/api/sessions/{sid}/file/session.json").status_code == 404
    assert client.get("/api/sessions/..%2F..%2Fetc/file/original").status_code == 404


def test_a_conversion_cut_off_by_a_restart_runs_again(tmp_path, monkeypatch):
    repo = tmp_path / "chimera"
    (repo / "target" / "release").mkdir(parents=True)
    monkeypatch.setattr("chimera_convert.chimera.find_cli", lambda r: None)
    sessions = tmp_path / "sessions"
    with TestClient(create_app(repo, sessions)) as c:
        sid = upload(c, tmp_path, "Pieni tähti,\ntuikkii yö").json()["id"]
        wait_done(c, sid)
    # as if the server had died mid-conversion
    p = sessions / sid / "session.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    s.update(status="running", stage="Tracking the pitch")
    p.write_text(json.dumps(s), encoding="utf-8")
    with TestClient(create_app(repo, sessions)) as c:
        assert wait_done(c, sid)["status"] == "done"


def test_a_session_marked_queued_while_the_server_runs_is_picked_up(tmp_path, monkeypatch):
    repo = tmp_path / "chimera"
    (repo / "target" / "release").mkdir(parents=True)
    monkeypatch.setattr("chimera_convert.chimera.find_cli", lambda r: None)
    sessions = tmp_path / "sessions"
    with TestClient(create_app(repo, sessions)) as c:
        sid = upload(c, tmp_path, "Pieni tähti,\ntuikkii yö").json()["id"]
        wait_done(c, sid)
        # marked by hand (or by another server process): nobody sent it to this worker
        p = sessions / sid / "session.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s.update(status="queued", stage="Queued", progress=0.0)
        p.write_text(json.dumps(s), encoding="utf-8")
        assert wait_done(c, sid)["status"] == "done"  # the list the app polls queues it


def test_backing_is_the_recording_less_its_voice(tmp_path):
    import numpy as np

    from chimera_convert.server import write_backing

    sr = 48000
    t = np.arange(sr) / sr
    band = 0.3 * np.sin(2 * np.pi * 110 * t).astype(np.float32)
    voice = 0.3 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    sf.write(tmp_path / "original.wav", band + voice, sr)
    s = {"files": {"original": "original.wav"}, "melody": {"offset": 0.1}}
    assert not write_backing(tmp_path, s, tmp_path / "backing.wav")  # nothing separated
    sf.write(tmp_path / "vocals.wav", voice, sr)
    assert write_backing(tmp_path, s, tmp_path / "backing.wav")
    y, _ = sf.read(tmp_path / "backing.wav")
    off = int(0.1 * sr)
    assert np.allclose(y[:off], 0)  # on the melody's clock
    assert np.max(np.abs(y[off:off + sr] - band)) < 2e-3


def test_the_render_estimate_never_claims_done_before_it_is(tmp_path):
    from chimera_convert.server import Renders, Store

    r = Renders(Store(tmp_path))
    now = time.time()
    seen = []
    for elapsed in (0, 5, 10, 20, 60, 600):
        r.jobs["x"] = {"state": "running", "started": now - elapsed, "length": 10, "expected": 10, "error": None, "render": None, "url": None}
        seen.append(r.status("x")["progress"])
    assert seen == sorted(seen) and seen[0] == 0 and abs(seen[2] - 0.95) < 0.01 and seen[-1] <= 0.99
    r.learn(2.0)
    assert r.speed() == 2.0
    r.learn(1.0)
    assert r.speed() == 1.5  # a running average: one slow render doesn't decide it


def test_the_thresholds_are_checked_before_the_notes(client, tmp_path):
    sid = upload(client, tmp_path, "Pieni tähti,\ntuikkii yö", review=True).json()["id"]
    s = wait_done(client, sid)
    assert s["status"] == "review" and not s.get("notes")
    g = client.get(f"/api/sessions/{sid}/singing").json()
    assert g["hop"] == 0.02 and len(g["db"]) == len(g["clarity"]) > 100
    assert g["current"] == g["suggested"] and set(g["current"]) == {"gate_db", "clarity", "rough", "hold"}
    assert g["voice_only"] is False and g["current"]["rough"] == 0.0  # a recording as is: only a clear pitch counts
    # the notes with chosen thresholds, from the kept analysis
    r = client.post(f"/api/sessions/{sid}/singing", json={"gate_db": -30, "clarity": 0.1, "rough": 0.5, "hold": 0.6})
    assert r.status_code == 200, r.text
    s = wait_done(client, sid)
    assert s["status"] == "done" and s["notes"], s.get("error")
    assert s["singing"] == {"gate_db": -30.0, "clarity": 0.1, "rough": 0.5, "hold": 0.6}
    # back to the thresholds and, without changing them, back to the same notes
    assert client.post(f"/api/sessions/{sid}/review", json={}).json()["status"] == "review"
    assert client.get(f"/api/sessions/{sid}").json()["notes"] == s["notes"]
    assert client.post(f"/api/sessions/{sid}/review", json={"back": True}).json()["status"] == "done"
    # a new language uses the kept analysis too
    assert client.post(f"/api/sessions/{sid}/lang", json={"lang": "fi"}).status_code == 200
    assert wait_done(client, sid)["status"] == "done"


def test_rap_style_is_kept_and_needs_the_alignment(client, tmp_path):
    wav = tmp_path / "rap.wav"
    sf.write(wav, voice(), SR)
    with open(wav, "rb") as f:
        r = client.post("/api/sessions", files={"audio": ("rap.wav", f, "audio/wav")},
                        data={"lyrics": "pieni tähti", "lang": "fi", "align": "none", "style": "rap"})
    assert r.status_code == 400 and "alignment" in r.json()["detail"]
    with open(wav, "rb") as f:
        r = client.post("/api/sessions", files={"audio": ("rap.wav", f, "audio/wav")},
                        data={"lyrics": "pieni tähti", "lang": "fi", "align": "none", "style": "polka"})
    assert r.status_code == 400


def fake_emissions(audio16, model_id, device):
    """A stand-in for the MMS aligner: every letter equally likely in every 20 ms frame (the CTC
    path is then spread evenly over the song), so the server's rap path runs without the model."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    vocab = {"<blank>": 0, **{c: i + 1 for i, c in enumerate(letters)}}
    T = int(len(audio16) / 16000 / 0.02)
    lp = np.full((T, len(vocab)), np.log(1.0 / len(vocab)), np.float32)
    return lp, 0.02, vocab, 0


def test_rap_settings_are_kept_and_the_style_can_change_without_a_new_analysis(client, tmp_path, monkeypatch):
    monkeypatch.setattr("chimera_convert.align.emissions", fake_emissions)
    calls = []
    import chimera_convert.pipeline as pl

    real = pl.analyze_audio
    monkeypatch.setattr(pl, "analyze_audio", lambda *a, **k: calls.append(1) or real(*a, **k))
    info = client.get("/api/info").json()
    assert info["separators"]["htdemucs"] and set(info["rap_defaults"]) == {"rest", "window", "min_rise", "nucleus", "keep_cents"}
    wav = tmp_path / "rap.wav"
    sf.write(wav, voice(), SR)
    with open(wav, "rb") as f:
        r = client.post("/api/sessions", files={"audio": ("rap.wav", f, "audio/wav")},
                        data={"lyrics": "Pieni tähti,\ntuikkii yö", "lang": "fi", "align": "mms", "style": "rap", "review": "false",
                              "rap": json.dumps({"rest": 3, "window": 0.05, "keep_cents": False})})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    s = wait_done(client, sid)
    assert s["status"] == "done", s.get("error")
    assert s["options"]["rap"] == {"rest": 1.0, "window": 0.05, "min_rise": 4.0, "nucleus": 0.7, "keep_cents": False}
    assert len(s["notes"]) == len(s["syllables"]) == 7 and all(n["syl"] is not None for n in s["notes"])  # no melismas
    assert s["vibrato"] == 0.0 and all(m == round(m) for m, _ in s["melody"]["notes"])  # keep_cents off
    assert len(calls) == 1
    # singing, then rap again with other settings: the cached analysis, no new one
    assert client.post(f"/api/sessions/{sid}/style", json={"style": "sing"}).status_code == 200
    s = wait_done(client, sid)
    assert s["status"] == "done" and s["options"]["style"] == "sing" and s["vibrato"] == 35.0, s.get("error")
    r = client.post(f"/api/sessions/{sid}/style", json={"style": "rap", "rap": {"rest": 0.2, "keep_cents": True}})
    assert r.status_code == 200
    s = wait_done(client, sid)
    assert s["status"] == "done" and s["options"]["rap"]["rest"] == 0.2 and s["options"]["rap"]["keep_cents"], s.get("error")
    assert len(calls) == 1
    # an edit keeps the style's cents
    ns = s["notes"]
    ns[0]["midi"] = 50.37
    m = client.put(f"/api/sessions/{sid}/notes", json={"notes": ns, "vibrato": 0}).json()["melody"]
    assert m["notes"][0][0] == 50.37
    assert client.post(f"/api/sessions/{sid}/style", json={"style": "polka"}).status_code == 400


def test_rap_needs_a_song_converted_with_the_alignment(client, tmp_path):
    sid = upload(client, tmp_path, "Pieni tähti,\ntuikkii yö").json()["id"]  # align: none
    assert wait_done(client, sid)["status"] == "done"
    r = client.post(f"/api/sessions/{sid}/style", json={"style": "rap"})
    assert r.status_code == 409 and "alignment" in r.json()["detail"]
