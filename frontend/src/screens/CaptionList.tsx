// Finished caption lines plus the words being spoken right now. When the speaker answers an
// audience question, the question is shown above the answer lines. Stays scrolled to the newest
// line unless the reader scrolls up.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Caption, QuestionRef } from "../lib/api";

function QuestionLine({ q }: { q: QuestionRef }) {
  return (
    <p className="mt-4 text-[0.75em] text-muted">
      Q{q.name ? ` (${q.name})` : ""}: {q.text}
    </p>
  );
}

export default function CaptionList({ captions, partial, answering, empty, textClass }: {
  captions: Caption[];
  partial: string;
  answering: QuestionRef | null;
  empty: React.ReactNode;
  textClass: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const pinnedRef = useRef(true);
  pinnedRef.current = pinned;

  useLayoutEffect(() => {
    if (pinned && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [captions.length, partial, answering?.id, pinned]);

  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { if (pinnedRef.current) el.scrollTop = el.scrollHeight; });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onScroll = () => {
    const el = box.current!;
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  };

  const last = captions[captions.length - 1];
  const pendingQuestion = answering && last?.answer_to?.id !== answering.id ? answering : null;

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={box} onScroll={onScroll} className="h-full overflow-y-auto px-5 py-4" aria-live="polite">
        {!captions.length && !partial && !answering ? (
          <div className="flex h-full items-center justify-center text-muted">{empty}</div>
        ) : (
          <div className={`space-y-2 ${textClass}`}>
            {captions.map((c, i) => (
              <div key={c.id}>
                {c.answer_to && c.answer_to.id !== captions[i - 1]?.answer_to?.id && <QuestionLine q={c.answer_to} />}
                <p className={i < captions.length - 3 ? "text-muted" : ""}>{c.text}</p>
              </div>
            ))}
            {pendingQuestion && <QuestionLine q={pendingQuestion} />}
            {partial && <p className="text-muted">{partial}</p>}
          </div>
        )}
      </div>
      {!pinned && (
        <button
          onClick={() => box.current?.scrollTo({ top: box.current.scrollHeight })}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-md bg-accent px-3 py-1.5 text-sm text-white"
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}
