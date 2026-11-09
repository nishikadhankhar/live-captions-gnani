import { useState } from "react";
import { go } from "../App";
import { api, saveSpeaker } from "../lib/api";

const input = "w-full rounded-md border border-line bg-surface px-3 py-2.5 text-base outline-none placeholder:text-muted";
const primary = "rounded-md bg-accent px-4 py-2.5 font-medium text-white disabled:opacity-50";

export default function Home() {
  const [title, setTitle] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const ev = await api.start(title.trim());
      saveSpeaker(ev);
      go(`/s/${ev.code}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const open = () => code.length >= 4 && go(`/e/${code}`);

  return (
    <main className="mx-auto max-w-sm px-5 pt-16">
      <h1 className="text-2xl font-semibold">Live Captions</h1>

      <label className="mb-1.5 mt-8 block text-sm text-muted" htmlFor="title">Event name</label>
      <input id="title" value={title} onChange={(e) => setTitle(e.target.value)}
             onKeyDown={(e) => e.key === "Enter" && start()} maxLength={80} className={input} />
      <button onClick={start} disabled={busy} className={`${primary} mt-3 w-full`}>
        {busy ? "Starting…" : "Start event"}
      </button>

      <label className="mb-1.5 mt-10 block text-sm text-muted" htmlFor="code">Join with a code</label>
      <div className="flex gap-2">
        <input id="code" value={code} maxLength={8}
               onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
               onKeyDown={(e) => e.key === "Enter" && open()} className={`${input} uppercase`} />
        <button onClick={open} className="rounded-md border border-line px-4">Join</button>
      </div>

      {error && <p role="alert" className="mt-4 text-sm text-danger">{error}</p>}
    </main>
  );
}
