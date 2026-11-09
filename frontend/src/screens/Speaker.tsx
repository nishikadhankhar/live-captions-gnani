// The speaker / organiser's screen (laptop, usually on the projector):
// QR code for the audience, the microphone, the live captions, and incoming questions.

import { useEffect, useRef, useState } from "react";
import { go } from "../App";
import { api, loadSpeaker, phonesCantReach, sttEngine, type Caption, type Question, type QuestionRef } from "../lib/api";
import { micSupported, streamMic } from "../lib/gnaniMic";
import { listen, speechSupported, type Listener } from "../lib/speech";
import { useSocket } from "../lib/useSocket";
import CaptionList from "./CaptionList";

const btn = "rounded-md border border-line px-3 py-1.5 text-sm";
const gnani = () => sttEngine() === "gnani";
const canCaption = () => (gnani() ? micSupported() : speechSupported());

export default function Speaker({ code }: { code: string }) {
  const [me] = useState(() => loadSpeaker(code));
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [listeners, setListeners] = useState(0);
  const [partial, setPartial] = useState("");
  const [micOn, setMicOn] = useState(false);
  const [micError, setMicError] = useState("");
  const [ended, setEnded] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [blocking, setBlocking] = useState<Question | null>(null);
  const [answering, setAnswering] = useState<QuestionRef | null>(null);
  const [notice, setNotice] = useState("");
  const rec = useRef<Listener | null>(null);
  const micWasOff = useRef(false);        // turn the mic back off after answering if it was off

  const { status, send } = useSocket(me ? `/ws/events/${code}/speak?token=${me.token}` : null, (ev) => {
    if (ev.type === "state") {
      setCaptions(ev.captions);
      setQuestions(ev.questions);
      setListeners(ev.event.listeners);
      setAnswering(ev.answering);
    } else if (ev.type === "answering") {
      setAnswering(ev.question);
    } else if (ev.type === "notice") {
      setNotice(ev.text);
    } else if (ev.type === "partial") {
      if (gnani()) setPartial(ev.text);                // with Gnani the server makes the captions
    } else if (ev.type === "caption") {
      setCaptions((c) => (c.some((x) => x.id === ev.caption.id) ? c : [...c, ev.caption]));
      if (gnani()) setPartial("");
    } else if (ev.type === "question") {
      setQuestions((q) => [...q, ev.question]);
    } else if (ev.type === "question_update") {
      setQuestions((q) => q.map((x) => (x.id === ev.question.id ? ev.question : x)));
    } else if (ev.type === "questions_removed") {
      setQuestions((q) => q.filter((x) => !ev.ids.includes(x.id)));
    } else if (ev.type === "listeners") {
      setListeners(ev.count);
    } else if (ev.type === "ended" || ev.type === "error") {
      setEnded(true);
    }
  });

  useEffect(() => () => rec.current?.stop(), []);

  const startMic = () => {
    setMicError("");
    if (rec.current) return;
    const onError = (m: string) => {
      setMicError(m);
      if (gnani() || m.includes("denied")) { rec.current?.stop(); rec.current = null; setMicOn(false); }
    };
    if (gnani()) {
      rec.current = streamMic({ path: `/ws/events/${code}/audio?token=${me!.token}`, onError });
      setMicOn(true);
      return;
    }
    rec.current = listen({
      lang: "en-IN",
      onPartial: (t) => { setPartial(t); send({ type: "partial", text: t }); },
      onFinal: (t) => { setPartial(""); send({ type: "final", text: t }); },
      onError: (m) => { setMicError(m); if (m.includes("denied")) { rec.current = null; setMicOn(false); } },
    });
    setMicOn(true);
  };

  const stopMic = () => {
    rec.current?.stop();
    rec.current = null;
    setMicOn(false);
    setPartial("");
  };

  // Answer a question out loud: the captions that follow are shown under the question.
  const answer = (q: Question) => {
    setNotice("");
    micWasOff.current = !micOn;
    send({ type: "answer", question_id: q.id });
    setAnswering({ id: q.id, text: q.text, name: q.name });
    startMic();                                      // inside the click: Chrome allows the mic
  };

  const doneAnswering = () => {
    send({ type: "answer", question_id: null });
    if (answering) {
      setQuestions((all) => all.map((x) => (x.id === answering.id ? { ...x, answered: true } : x)));
    }
    setAnswering(null);
    if (micWasOff.current) stopMic();
  };

  const end = async () => {
    rec.current?.stop();
    await api.end(code, me!.token).catch(() => {});
    setEnded(true);
  };

  const block = async (q: Question) => {
    setBlocking(null);
    try {
      const r = await api.block(code, me!.token, q.id);
      setQuestions((all) => all.filter((x) => !r.removed.includes(x.id)));
    } catch { /* the question was already gone */ }
  };

  const mark = (q: Question) => {
    setQuestions((all) => all.map((x) => (x.id === q.id ? { ...x, answered: !q.answered } : x)));
    api.answered(code, me!.token, q.id, !q.answered).catch(() => {});
  };

  if (!me || ended) {
    return (
      <main className="px-5 pt-16 text-center">
        <p className="text-lg">{ended ? "Event ended." : "Only the browser that started this event can control it."}</p>
        <button onClick={() => go(ended ? "/" : `/e/${code}`)} className={`${btn} mt-4`}>
          {ended ? "Start another" : "Open captions"}
        </button>
      </main>
    );
  }

  const open = questions.filter((q) => !q.answered).slice().reverse();
  const done = questions.filter((q) => q.answered).slice().reverse();

  return (
    <div className="flex h-full flex-col lg:flex-row">
      <aside className="flex shrink-0 flex-col gap-3 border-line p-5 lg:w-[380px] lg:border-r">
        <h1 className="text-xl font-semibold">{me.title || "Untitled event"}</h1>

        <div className="rounded-md bg-white p-3">
          <img src={api.qrUrl(code)} alt={`QR code for event ${code}`} className="mx-auto w-full max-w-[320px]" />
        </div>
        {phonesCantReach() && (
          <p role="alert" className="text-sm text-danger">
            Phones can't open this QR code (localhost). Start the app with ./demo.sh.
          </p>
        )}
        <p className="break-all text-sm text-muted">{api.joinLink(code)}</p>
        <p className="text-sm text-muted">{listeners} reading</p>

        <div className="mt-auto space-y-2">
          {micError && <p role="alert" className="text-sm text-danger">{micError}</p>}
          {!canCaption() && (
            <p className="text-sm text-danger">{gnani() ? "This browser can't use the microphone." : "Captions need Google Chrome."}</p>
          )}
          {status !== "live" && <p className="text-sm text-muted">Connecting…</p>}
          <button onClick={() => (micOn ? stopMic() : startMic())} disabled={!canCaption()} aria-pressed={micOn}
                  className={`w-full rounded-md px-4 py-3 text-lg font-medium text-white disabled:opacity-50 ${micOn ? "bg-danger" : "bg-accent"}`}>
            {micOn ? "Stop captioning" : "Start captioning"}
          </button>
          <button onClick={() => setConfirmEnd(true)} className={`${btn} w-full`}>End event</button>
        </div>
      </aside>

      <section className="flex min-h-0 flex-1 flex-col">
        {answering && (
          <div className="flex items-center gap-4 border-b border-line bg-surface px-5 py-3" role="status">
            <p className="min-w-0 flex-1 truncate">
              <span className="text-muted">Answering{answering.name ? ` ${answering.name}` : ""}: </span>
              {answering.text}
            </p>
            <button onClick={doneAnswering} className="shrink-0 rounded-md bg-ok px-4 py-2 font-medium text-white">Done</button>
          </div>
        )}
        {notice && <p className="border-b border-line px-5 py-2 text-sm text-danger">{notice}</p>}

        <CaptionList captions={captions} partial={partial} answering={answering} textClass="caption-xl" empty={null} />

        <div className="max-h-[45%] min-h-[160px] overflow-y-auto border-t border-line px-5 py-4">
          <h2 className="mb-2 font-medium">Questions{open.length ? ` (${open.length})` : ""}</h2>
          <ul className="divide-y divide-line">
            {[...open, ...done].map((q) => (
              <li key={q.id} className={`flex items-center gap-2 py-2.5 ${q.answered ? "opacity-50" : ""}`}>
                <div className="min-w-0 flex-1">
                  <p>{q.text}</p>
                  <p className="text-sm text-muted">
                    {q.name || "Anonymous"}, {new Date(q.at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
                {!q.answered && answering?.id !== q.id && (
                  <button onClick={() => answer(q)} disabled={!canCaption()}
                          className="shrink-0 rounded-md bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-50">
                    Answer
                  </button>
                )}
                {answering?.id !== q.id && (
                  <button onClick={() => mark(q)} className={`${btn} shrink-0`}>{q.answered ? "Undo" : "Mark answered"}</button>
                )}
                <button onClick={() => setBlocking(q)} className={`${btn} shrink-0 text-danger`}>Block</button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {blocking && (
        <Confirm text={`Block ${blocking.name || "this person"}? Their questions will be removed and new ones ignored.`}
                 action="Block" onConfirm={() => block(blocking)} onCancel={() => setBlocking(null)} />
      )}
      {confirmEnd && (
        <Confirm text="End the event? Captions and questions will be deleted."
                 action="End event" onConfirm={end} onCancel={() => setConfirmEnd(false)} />
      )}
    </div>
  );
}

function Confirm({ text, action, onConfirm, onCancel }: {
  text: string; action: string; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div role="dialog" aria-label={action} onClick={(e) => e.stopPropagation()}
           className="w-full max-w-sm rounded-md border border-line bg-surface p-5">
        <p>{text}</p>
        <div className="mt-4 flex gap-2">
          <button onClick={onCancel} className="flex-1 rounded-md border border-line px-4 py-2">Cancel</button>
          <button onClick={onConfirm} className="flex-1 rounded-md bg-danger px-4 py-2 font-medium text-white">{action}</button>
        </div>
      </div>
    </div>
  );
}
