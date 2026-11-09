import { useEffect, useRef, useState } from "react";
import { api, LANG_NAMES, type Info, type Summary } from "./api.ts";
import { Editor } from "./Editor.tsx";
import { NewSong } from "./NewSong.tsx";

const active = (x: Summary) => x.status === "queued" || x.status === "running";

export function App() {
  const [info, setInfo] = useState<Info | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [list, setList] = useState<Summary[]>([]);
  const [current, setCurrent] = useState<string | null>(() => new URLSearchParams(location.search).get("s"));
  const listRef = useRef(list);
  listRef.current = list;

  const refresh = () =>
    api
      .sessions()
      .then((l) => {
        setList(l);
        setOnline(true);
      })
      .catch(() => setOnline(false));

  // the server and the song list: every 1.5 s while a song is being processed, else every 5 s
  useEffect(() => {
    api.info().then(setInfo).catch(() => setOnline(false));
    refresh();
    let t = 0;
    const tick = async () => {
      await refresh();
      t = window.setTimeout(tick, listRef.current.some(active) ? 1500 : 5000);
    };
    t = window.setTimeout(tick, 1500);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    if (online && !info) api.info().then(setInfo).catch(() => {});
  }, [online]);
  useEffect(() => {
    history.replaceState(null, "", current ? `?s=${current}` : location.pathname);
  }, [current]);

  const busy = list.filter(active);
  return (
    <div className="app">
      <header className="topbar">
        <h1>
          CHIMERA <span>converter</span>
        </h1>
        <span className="dim">recording + lyrics → notes for Chimera</span>
        <span className="spacer" />
        {busy.length > 0 && (
          <button className="activity" onClick={() => setCurrent(busy[0].id)} title="Show the song being processed">
            <i className="pulse" /> Processing {busy.length === 1 ? `“${busy[0].title}”` : `${busy.length} songs`} · {Math.round(busy[0].progress * 100)} %
          </button>
        )}
        <span className={`server ${online === false ? "off" : online ? "on" : ""}`}>
          <i />
          {online === false ? "Server not running: start scripts\\start_app.bat" : online ? "Server running" : "Connecting …"}
        </span>
        {info && online && (
          <span className="dim">
            {info.gpu ?? "no GPU (CPU)"} · Chimera {info.chimera_cli ? "✓" : "missing"}
          </span>
        )}
      </header>
      <aside className="side">
        <button className={`new ${current === null ? "on" : ""}`} onClick={() => setCurrent(null)}>
          + New song
        </button>
        <ul>
          {list.map((x) => (
            <li key={x.id} className={`${x.id === current ? "on" : ""} st-${x.status}`} onClick={() => setCurrent(x.id)}>
              <b>{x.title}</b>
              <span className="meta">
                <StatusBadge s={x} />
                <span className="dim">
                  {LANG_NAMES[x.lang] ?? x.lang}
                  {x.duration ? ` · ${Math.round(x.duration)} s` : ""}
                </span>
              </span>
              {active(x) && (
                <div className="bar mini">
                  <div style={{ width: `${Math.max(3, Math.round(x.progress * 100))}%` }} />
                </div>
              )}
            </li>
          ))}
        </ul>
        {list.length === 0 && online && <p className="dim empty">No songs yet. Add one with “New song”.</p>}
      </aside>
      <main className="main">
        {current === null ? (
          <NewSong
            onCreated={(id) => {
              refresh();
              setCurrent(id);
            }}
          />
        ) : (
          <Editor
            id={current}
            info={info}
            onChanged={refresh}
            onStatus={(x) =>
              setList((l) => l.map((y) => (y.id === x.id ? { ...y, status: x.status, stage: x.stage, progress: x.progress, error: x.error, lang: x.lang } : y)))
            }
          />
        )}
      </main>
    </div>
  );
}

export function StatusBadge({ s }: { s: Pick<Summary, "status" | "stage" | "progress"> }) {
  if (s.status === "queued") return <span className="badge queued">Waiting</span>;
  if (s.status === "running") return <span className="badge running">{s.stage} {Math.round(s.progress * 100)} %</span>;
  if (s.status === "review") return <span className="badge review">Check</span>;
  if (s.status === "error") return <span className="badge error">Failed</span>;
  return <span className="badge done">Ready</span>;
}
