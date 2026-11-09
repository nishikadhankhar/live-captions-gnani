// A WebSocket that reconnects by itself (venue Wi-Fi drops) and hands every event to `onEvent`.

import { useEffect, useRef, useState } from "react";
import { wsUrl } from "./api";

export type Status = "connecting" | "live" | "reconnecting" | "gone";

export function useSocket(path: string | null, onEvent: (ev: any) => void) {
  const [status, setStatus] = useState<Status>("connecting");
  const sock = useRef<WebSocket | null>(null);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!path) return;
    let stop = false;
    let retry = 0;
    let timer: number | undefined;

    const open = () => {
      const ws = new WebSocket(wsUrl(path));
      sock.current = ws;
      ws.onopen = () => { retry = 0; setStatus("live"); };
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data);
        if (ev.type === "error" || ev.type === "ended") {
          stop = true;
          setStatus("gone");
        }
        handler.current(ev);
      };
      ws.onclose = () => {
        if (stop) return;
        setStatus("reconnecting");
        retry = Math.min(retry + 1, 5);
        timer = window.setTimeout(open, 500 * 2 ** retry);    // 1 s, 2 s … up to 16 s
      };
    };
    open();
    return () => {
      stop = true;
      window.clearTimeout(timer);
      sock.current?.close();
    };
  }, [path]);

  const send = (event: object) => {
    if (sock.current?.readyState === WebSocket.OPEN) sock.current.send(JSON.stringify(event));
  };
  return { status, send };
}
