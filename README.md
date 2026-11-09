# Live Captions

Browser-based live captioning for in-person events, with a way for the audience to ask
questions. Not a call, not a chat: the speaker talks, everyone reads along on their phone.

1. The speaker (or organiser) opens the app on a laptop and starts an event.
   A big **QR code** appears; put it on the projector.
2. People in the audience **scan it** with their phone camera. A page opens straight away:
   no app, no sign-up, no name.
3. The speaker taps **Start captioning** and talks. Everything they say appears **live** on
   every phone: words as they're spoken, then the finished line.
   *"Hello, my name is Astha Malik"* → shows up on every phone as they say it.
4. Anyone can tap **Ask a question**. It appears on the speaker's screen with three options:
   - **🎙 Answer**: the speaker answers out loud. Every phone shows the question as a card in the
     captions with the spoken answer underneath. Tap **✓ Done** when finished; the question is
     marked answered and the mic returns to how it was.
   - **✓ Mark answered** without speaking.
   - **🚫 Block** the person: all their questions disappear and nothing more they send gets
     through. They keep reading the captions and aren't told they were blocked.
5. **End event** stops the captions on every phone and deletes everything.

## Run it

```bash
./demo.sh            # starts everything, prints a phone link, opens Chrome
```

`demo.sh` also creates a temporary public **https** link (Cloudflare quick tunnel) so phones on
**any** network, including mobile data, can open the QR code. It disappears on Ctrl+C.
See [DEMO.md](DEMO.md) for the live-demo checklist.

By hand:

```bash
cd backend && pip3 install -r requirements.txt && ./run.sh     # API on :8000
cd frontend && npm install && npm run dev                      # http://localhost:5173
```

**Use Google Chrome on the speaker's laptop**: the captions come from Chrome's built-in
speech recognition (it needs internet). Attendees can use any phone browser.

## Test

```bash
cd backend && python3 -m pytest tests/ -q --timeout 20     # 29 tests, ~1 s
cd frontend && npx tsc --noEmit                             # type-check
```

## How it works

```
Speaker laptop (Chrome)                 Server                      Attendee phones
mic → speech recognition ── partial ──▶  /ws/.../speak  ── partial ──▶  /ws/.../listen
                          ── final ───▶  keeps last 200 ── caption ──▶  (late arrivals get
                                         lines                           the last 50)
questions + people count ◀──────────────               ◀── POST /questions ── "Ask a question"
```

| Endpoint | Who | What |
|---|---|---|
| `POST /api/events` | speaker | start an event → code + secret speaker token |
| `GET /api/events/{code}/qr.svg` | speaker | QR code (points at the phone link) |
| `WS /ws/events/{code}/speak?token=` | speaker | send `{"type":"partial"\|"final","text"}`; answer a question with `{"type":"answer","question_id":3}` … `{"type":"answer","question_id":null}`; receive questions and how many people are reading |
| `PATCH /api/events/{code}/questions/{id}` | speaker | mark answered (`x-token` header) |
| `POST /api/events/{code}/questions/{id}/block` | speaker | block the phone that asked it: removes all its questions, drops any new ones (`x-token` header) |
| `DELETE /api/events/{code}` | speaker | end the event (`x-token` header) |
| `GET /api/events/{code}` | attendee | title, live or not |
| `WS /ws/events/{code}/listen` | attendee | recent captions, then `partial` / `caption` live (a caption's `answer_to` names the question it answers); `answering`, `live`, `ended` |
| `POST /api/events/{code}/questions` | attendee | `{"text", "name"?, "client_id"}`; one per 5 s per phone |

No database and no accounts: events live in memory and are deleted when ended or after
6 hours idle. Audio never leaves the speaker's browser except to Chrome's speech recognition.

## Files

```
backend/app/
  main.py     routes
  events.py   events, captions, questions, sending to phones
frontend/src/
  screens/Home.tsx         start an event
  screens/Speaker.tsx      QR code, mic, live captions, questions
  screens/Attendee.tsx     live captions + "Ask a question"
  screens/CaptionList.tsx  the caption view (pinned to the newest line)
  lib/speech.ts            Chrome speech recognition
  lib/useSocket.ts         WebSocket with auto-reconnect
  lib/api.ts               backend calls, phone link
demo.sh                    one-command demo with a public phone link
```
