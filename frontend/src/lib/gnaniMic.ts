// Streams the speaker's microphone to the server as 16 kHz mono 16-bit PCM. The server relays
// it to Gnani's speech-to-text and sends the captions to every phone (and back to this screen).
// Used when /api/config says "stt": "gnani"; otherwise lib/speech.ts (Chrome) makes captions.

import { wsUrl } from "./api";
import type { Listener } from "./speech";

const RATE = 16000;

// Runs on the audio thread: float samples -> 16 kHz Int16, posted in 64 ms blocks.
const WORKLET = `
class Pcm16 extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    this.step = opts.processorOptions.inRate / ${RATE};   // 1 when the context already runs at 16 kHz
    this.pos = 0;
    this.out = new Int16Array(1024);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    while (this.pos < ch.length) {
      const i = Math.floor(this.pos), f = this.pos - i;
      const a = ch[i], b = i + 1 < ch.length ? ch[i + 1] : a;
      const s = Math.max(-1, Math.min(1, a + (b - a) * f));
      this.out[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === this.out.length) {
        this.port.postMessage(this.out.buffer, [this.out.buffer]);
        this.out = new Int16Array(1024);
        this.n = 0;
      }
      this.pos += this.step;
    }
    this.pos -= ch.length;
    return true;
  }
}
registerProcessor("pcm16", Pcm16);
`;

export const micSupported = () =>
  typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && "AudioWorkletNode" in window;

export function streamMic(opts: { path: string; onError: (message: string) => void }): Listener {
  let stopped = false;
  let ws: WebSocket | null = null;
  let ctx: AudioContext | null = null;
  let stream: MediaStream | null = null;
  let retries = 0;

  const fail = (m: string) => { if (!stopped) opts.onError(m); };

  const connect = () => {
    if (stopped) return;
    const sock = new WebSocket(wsUrl(opts.path));
    sock.binaryType = "arraybuffer";
    ws = sock;
    sock.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data);
        if (ev.type === "ready") retries = 0;
        if (ev.type === "error") { stopped = true; opts.onError(ev.error); }
      } catch { /* not JSON */ }
    };
    sock.onclose = () => {
      if (stopped || ws !== sock) return;
      if (retries++ < 4) setTimeout(connect, 1000 * retries);   // venue Wi-Fi blips
      else fail("Lost the connection to the server. Stop and start captioning again.");
    };
  };

  (async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      fail("Microphone permission was denied. Allow it in the browser settings.");
      return;
    }
    if (stopped) { stream.getTracks().forEach((t) => t.stop()); return; }
    try {
      ctx = new AudioContext({ sampleRate: RATE });
    } catch {
      ctx = new AudioContext();                      // the worklet resamples to 16 kHz
    }
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const node = new AudioWorkletNode(ctx, "pcm16", { processorOptions: { inRate: ctx.sampleRate } });
    node.port.onmessage = (m) => {
      if (ws?.readyState === WebSocket.OPEN) ws.send(m.data as ArrayBuffer);
    };
    ctx.createMediaStreamSource(stream).connect(node);
    connect();
  })().catch((e) => fail(`Microphone: ${e}`));

  return {
    stop() {
      stopped = true;
      const sock = ws;
      ws = null;
      if (sock?.readyState === WebSocket.OPEN) {
        sock.send(JSON.stringify({ type: "stop" }));   // the server finishes the last sentence
        setTimeout(() => sock.close(), 500);
      } else {
        sock?.close();
      }
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close().catch(() => {});
    },
    setLang() { /* Gnani detects the language itself (indic-auto) */ },
  };
}
