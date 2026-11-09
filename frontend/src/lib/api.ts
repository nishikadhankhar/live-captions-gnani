// Talking to the backend.

export interface QuestionRef { id: number; text: string; name: string | null }
export interface Caption { id: number; text: string; at: number; answer_to: QuestionRef | null }
export interface Question { id: number; text: string; name: string | null; at: number; answered: boolean }
export interface EventInfo { code: string; title: string; live: boolean; listeners: number }
export interface Started { code: string; title: string; token: string; join_url: string }

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers["x-token"] = token;
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg ?? detail;
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  start: (title: string) => call<Started>("/api/events", { method: "POST", body: JSON.stringify({ title }) }),
  info: (code: string) => call<EventInfo>(`/api/events/${code}`),
  ask: (code: string, text: string, name: string) =>
    call<{ ok: boolean }>(`/api/events/${code}/questions`, {
      method: "POST", body: JSON.stringify({ text, name: name || null, client_id: clientId() }),
    }),
  answered: (code: string, token: string, id: number, answered: boolean) =>
    call<Question>(`/api/events/${code}/questions/${id}`, { method: "PATCH", body: JSON.stringify({ answered }) }, token),
  block: (code: string, token: string, id: number) =>
    call<{ ok: boolean; removed: number[] }>(`/api/events/${code}/questions/${id}/block`, { method: "POST" }, token),
  end: (code: string, token: string) => call<{ ok: boolean }>(`/api/events/${code}`, { method: "DELETE" }, token),
  qrUrl: (code: string) => `/api/events/${code}/qr.svg?base=${encodeURIComponent(phoneBase())}`,
  joinLink: (code: string) => `${phoneBase()}/e/${code}`,
};

export function wsUrl(path: string) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
}

// --------------------------------------------------------------------------- //
// Where phones should go: the tunnel / Wi-Fi address from the backend, else this page.
let phoneUrl: string | null = null;

export async function loadConfig() {
  try {
    phoneUrl = (await call<{ phone_url: string | null }>("/api/config")).phone_url;
  } catch { /* backend down: fall back to this page's address */ }
}

export const phoneBase = () => phoneUrl ?? window.location.origin;

/** True when the QR would point at "localhost", which no phone can open. */
export const phonesCantReach = () =>
  !phoneUrl && ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);

// --------------------------------------------------------------------------- //
// The speaker's secret stays in this browser tab, so a refresh keeps control of the event.
const KEY = "captions:speaker";

export function saveSpeaker(s: Started) {
  try { sessionStorage.setItem(`${KEY}:${s.code}`, JSON.stringify(s)); } catch { /* private mode */ }
}

export function loadSpeaker(code: string): Started | null {
  try { return JSON.parse(sessionStorage.getItem(`${KEY}:${code}`) || "null"); } catch { return null; }
}

/** A random id per phone, so the server can slow down question spam without accounts. */
function clientId(): string {
  try {
    let id = localStorage.getItem("captions:client");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("captions:client", id);
    }
    return id;
  } catch {
    return "anon-" + Math.random().toString(36).slice(2);
  }
}
