// Live speech recognition in the browser (Chrome, Edge, Android, iOS Safari).
// Sends words-so-far ("partial") while someone talks and the finished sentence ("final")
// with how long it took to say, which the server uses for the "slow down" nudge.

type Rec = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
};

export const speechSupported = () =>
  typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

export interface Listener {
  stop(): void;
  setLang(lang: string): void;
}

export function listen(opts: {
  lang: string;                                   // "en-IN", "hi-IN"
  onPartial: (text: string) => void;
  onFinal: (text: string, durationMs: number) => void;
  onError: (message: string) => void;
}): Listener {
  const Ctor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  let rec: Rec | null = null;
  let stopped = false;
  let lang = opts.lang;
  let started = 0;                                // when the current sentence began

  const begin = () => {
    rec = new Ctor() as Rec;
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        const text = r[0].transcript.trim();
        if (!started && text) started = performance.now();
        if (r.isFinal) {
          if (text) opts.onFinal(text, Math.round(performance.now() - (started || performance.now())));
          started = 0;
        } else {
          interim += text + " ";
        }
      }
      if (interim.trim()) opts.onPartial(interim.trim());
    };
    rec.onerror = (e: any) => {
      if (e.error === "no-speech" || e.error === "aborted") return;   // silence: just keep going
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        stopped = true;
        opts.onError("Microphone permission was denied. Allow it in the browser settings.");
      } else {
        opts.onError(`Speech recognition: ${e.error}`);
      }
    };
    // Browsers end recognition after a pause or ~60 s: restart until the user stops.
    rec.onend = () => {
      if (!stopped) setTimeout(() => !stopped && begin(), 150);
    };
    try {
      rec.start();
    } catch (err) {
      opts.onError(String(err));
    }
  };
  begin();

  return {
    stop() {
      stopped = true;
      rec?.stop();
    },
    setLang(l: string) {
      lang = l;
      rec?.abort();                               // onend restarts it in the new language
    },
  };
}
