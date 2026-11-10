# Live Captions

Hackathon project (Devlympics, "Bridge the Gap"): browser-based live captioning for
in-person events, plus audience questions. The speaker shows a QR code; attendees scan it and
read the speaker's words live on their phone, and can send a question. README.md has the API.

## Scope (decided by the team, keep it this small)

- **This is not a chat, call or messaging app.** Only: speaker → live captions → phones, and
  attendee → question → speaker.
- No accounts, no attendee names required (name on a question is optional), no tone tags,
  alerts, AI summaries, translation or voice output. These were built once and deliberately
  removed. Don't add features without the team asking.
- Earlier ideas (Scheme Saathi; a deaf-user "Live Room" with chat) were dropped. Don't bring them back.

## UI style (the team asked for this explicitly)

Plain and functional. No emoji, no decorative icons or logos, no pill badges, no big rounded
cards, no coloured info boxes, no uppercase/letter-spaced labels, no animations, no marketing or
helper copy. System font, small radius (`rounded-md`), short plain labels. The speaker screen
shows the event name, the QR code alone in a white box, and nothing else decorative.

## Commands

```bash
./demo.sh                                        # backend :8000 + frontend :5173 + public phone link
cd backend && python3 -m pytest tests/ -q --timeout 20
cd frontend && npx tsc --noEmit
```

Always pass `--timeout`: a WebSocket test waiting for an event that never comes hangs forever.

## How it fits together

- Captions come from **Gnani's realtime speech-to-text** when `GNANI_API_KEY` is set
  (`/api/config` → `"stt": "gnani"`). The speaker's browser (`lib/gnaniMic.ts`) streams the mic
  as PCM16 mono 16 kHz over `/ws/events/{code}/audio`; `backend/app/gnani.py` re-frames it to
  the 1024-byte frames Gnani requires and relays it (the key can't go to the browser), then
  the server itself sends `partial` / `caption` to everyone. Gnani facts learned the hard way:
  streaming rejects a language list (`en-IN,hi-IN`); `indic-auto` sometimes wrote real-mic Hindi
  in Punjabi letters, so the default is `hi-IN` (English still comes out in Latin letters); word-by-word
  partials need the undocumented `x-partials: true` header, and then finals arrive as
  `final_transcript` (not `transcript`); a session ends after 15 min, so the relay reconnects.
- Without a key (or `CAPTIONS_ENGINE=browser`) captions come from **Chrome's speech
  recognition** (`lib/speech.ts`), which sends `partial` / `final` over `/ws/events/{code}/speak`.
- The server (`backend/app/events.py`) fans them out to every `/ws/events/{code}/listen` phone,
  in parallel with a per-send timeout so one slow phone can't stall the rest. It keeps the last
  200 lines; late arrivals get the last 50.
- Questions: `POST /api/events/{code}/questions` → pushed to the speaker's socket only. One per
  5 s per phone (`client_id`, a random id kept in the phone's localStorage).
- Blocking: the speaker blocks the phone behind a question (`client_id`, stored server-side only
  and never sent to the speaker). Its questions are removed and new ones are silently dropped
  with a normal "ok", so a troll isn't prompted to clear their browser and return with a new id.
  Clearing site data or a private tab still gives a new id: acceptable for events.
- Answering out loud: the speaker sends `{"type":"answer","question_id":N}`; while set, every new
  caption carries `answer_to` (question id/text/name, never the phone id), so phones draw the
  question card with the answer lines under it, late joiners included. `question_id: null`
  (Done) marks it answered. Blocking the question being answered cancels answering.
- Phones reach the laptop through a Cloudflare quick tunnel started by `demo.sh`, which writes the
  link to `.public_url`; `/api/config` serves it and the QR code uses it. Without it, the QR
  points at localhost and the speaker screen shows a warning.
- The speaker's secret token is kept in sessionStorage (per tab), so a refresh keeps control.

## Testing gotchas

- Don't test speaker + phones with FastAPI's TestClient WebSockets: it runs each socket on its
  own event loop, which a real server never does. `tests/test_api.py` runs a real uvicorn
  server in a thread with a small `Socket` helper; keep live tests in that style.
- A test script acting as a phone must keep reading incoming events, or its buffer fills and
  it gets disconnected.
- The browser pane used for checking has no microphone: drive captions from a Python
  `websockets` script using the speaker token (for Gnani, stream PCM into `/audio`).
- Gnani tests use `FakeGnani` (a local websockets server); never call the real API from tests.
- `demo.sh` uses ports 8000/5173 (and 5174 in wifi mode). Test elsewhere if it's running.

## Secrets

`backend/.env` (GNANI_API_KEY) and `.public_url` are gitignored. Scan staged files before pushing.

## Commits

End commit messages with:
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
