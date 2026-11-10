# Live Captions: real-time Hindi and English captions for every listener

**Built on Gnani's Prisma v3.0 real-time speech-to-text.**

## The problem

An estimated 6 crore people in India live with hearing loss, and many more who struggle to follow a
speaker in a noisy auditorium, a large classroom or a crowded event. Live captioning today
means expensive human captioners, apps everyone has to install, or tools that only understand
English. Real Indian speakers switch between Hindi and English mid-sentence, and most caption
tools break on that.

## The solution

A speaker opens Live Captions on a laptop and shows a QR code. The audience scans it with any
phone browser: no app, no sign-up, no name. Everything the speaker says appears on every phone
**word by word as it is spoken**, then as a clean punctuated sentence a moment after each pause.

- **Hindi, English and Hinglish**: Hindi in Devanagari, English words kept in English inside
  Hindi sentences ("आज का session technology के बारे में है").
- **Audience questions**: anyone can send a question from their phone. When the speaker
  answers out loud, the spoken answer is captioned under that question on every phone.
- **Moderation**: the speaker can block a troll; their questions disappear silently.
- **Private by design**: no accounts, no database, no recordings. Ending the event deletes
  everything.

## How it uses Gnani

The speaker's browser streams the microphone (16 kHz PCM) to our FastAPI server, which relays it
to Gnani's streaming endpoint (`wss://api.vachana.ai/stt/v3/stream`) and fans the captions out to
every phone over WebSockets. The API key never reaches the browser.

- **Prisma v3.0**, `format=codemix` for natural Hinglish output.
- **Live partial transcripts** (`x-partials`) for word-by-word captions, with finished sentences
  about 0.1 s after the speaker pauses.
- Re-frames browser audio into the exact 1,024-byte frames Gnani requires, and reconnects
  automatically when a stream reaches its 15-minute limit.
- Falls back to Chrome's speech recognition if no Gnani key is configured.

## Impact and what's next

One laptop makes any talk, lecture or panel accessible to everyone in the room, in the
languages Indians actually speak. Next: a language picker for Tamil, Telugu, Bengali and the
other Indic languages Prisma supports, and a saved transcript the speaker can share afterwards.

**Stack**: React + Vite, FastAPI, WebSockets, Gnani Prisma v3.0 STT. 37 automated tests.
**Run it**: `./demo.sh` (see README.md).
