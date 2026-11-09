// What an attendee sees after scanning the QR code: live captions, and a way to ask a question.

import { useEffect, useState } from "react";
import { api, type Caption, type QuestionRef } from "../lib/api";
import { useSocket } from "../lib/useSocket";
import CaptionList from "./CaptionList";

export default function Attendee({ code }: { code: string }) {
  const [title, setTitle] = useState("");
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [partial, setPartial] = useState("");
  const [answering, setAnswering] = useState<QuestionRef | null>(null);
  const [live, setLive] = useState(false);
  const [gone, setGone] = useState<"" | "ended" | "missing">("");
  const [asking, setAsking] = useState(false);
  const [sent, setSent] = useState(false);

  const { status } = useSocket(`/ws/events/${code}/listen`, (ev) => {
    if (ev.type === "state") {
      setTitle(ev.event.title);
      setLive(ev.event.live);
      setCaptions(ev.captions);
      setPartial(ev.partial || "");
      setAnswering(ev.answering);
    } else if (ev.type === "answering") {
      setAnswering(ev.question);
    } else if (ev.type === "partial") {
      setPartial(ev.text);
    } else if (ev.type === "caption") {
      setCaptions((c) => (c.some((x) => x.id === ev.caption.id) ? c : [...c.slice(-199), ev.caption]));
      setPartial("");
    } else if (ev.type === "live") {
      setLive(ev.live);
      if (!ev.live) setPartial("");
    } else if (ev.type === "ended") {
      setGone("ended");
    } else if (ev.type === "error") {
      setGone("missing");
    }
  });

  useEffect(() => {
    if (!sent) return;
    const t = window.setTimeout(() => setSent(false), 3000);
    return () => window.clearTimeout(t);
  }, [sent]);

  if (gone) {
    return (
      <main className="px-5 pt-16 text-center">
        <p className="text-lg">{gone === "ended" ? "This event has ended." : "Event not found."}</p>
      </main>
    );
  }

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
        <p className="truncate font-medium">{title || "Untitled event"}</p>
        <p className="shrink-0 text-sm text-muted">
          {status !== "live" ? "Connecting…" : live ? "Live" : "Not started"}
        </p>
      </header>

      <CaptionList captions={captions} partial={partial} answering={answering} textClass="caption"
                   empty={<p>{live ? "" : "Waiting for the speaker"}</p>} />

      <footer className="border-t border-line px-5 pb-[max(env(safe-area-inset-bottom),12px)] pt-3">
        {sent && <p role="status" className="mb-2 text-center text-sm text-ok">Question sent</p>}
        <button onClick={() => setAsking(true)} className="w-full rounded-md bg-accent px-4 py-3 font-medium text-white">
          Ask a question
        </button>
      </footer>

      {asking && <AskSheet code={code} onClose={() => setAsking(false)} onSent={() => { setAsking(false); setSent(true); }} />}
    </div>
  );
}

function AskSheet({ code, onClose, onSent }: { code: string; onClose: () => void; onSent: () => void }) {
  const [text, setText] = useState("");
  const [name, setName] = useState(() => {
    try { return localStorage.getItem("captions:name") || ""; } catch { return ""; }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.ask(code, text.trim(), name.trim());
      try { localStorage.setItem("captions:name", name.trim()); } catch { /* private mode */ }
      onSent();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const field = "w-full rounded-md border border-line bg-bg px-3 py-2.5 outline-none placeholder:text-muted";

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/60 sm:items-center" onClick={onClose}>
      <div role="dialog" aria-label="Ask a question" onClick={(e) => e.stopPropagation()}
           className="w-full max-w-lg border-t border-line bg-surface p-5 sm:rounded-md sm:border">
        <textarea value={text} onChange={(e) => setText(e.target.value)} autoFocus rows={3} maxLength={300}
                  placeholder="Your question" aria-label="Your question" className={`${field} resize-none text-base`} />
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40}
               placeholder="Name (optional)" aria-label="Name (optional)" className={`${field} mt-2`} />
        {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
        <div className="mt-3 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-md border border-line px-4 py-2.5">Cancel</button>
          <button onClick={submit} disabled={busy || !text.trim()}
                  className="flex-1 rounded-md bg-accent px-4 py-2.5 font-medium text-white disabled:opacity-50">
            {busy ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
