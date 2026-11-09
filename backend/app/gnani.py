"""Captions from Gnani's realtime speech-to-text (Prisma v3.0).

Browsers can't send Gnani's auth header, and the key must stay secret, so the speaker's
browser streams raw microphone audio to this server, which relays it to Gnani:

    speaker mic --PCM16 16 kHz--> /ws/events/{code}/audio --> wss://api.vachana.ai/stt/v3/stream
                                                           <-- {"type":"transcript","text":...}

With the (undocumented) `x-partials: true` header Gnani streams the words so far about every
0.6 s (`partial_transcript`) and a punctuated line when the speaker pauses (`final_transcript`;
`transcript` without partials). It closes a session after 15 minutes, so we reconnect while
the speaker is still sending. Docs: https://docs.gnani.ai/api/STT/stt-websocket
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

import websockets
from fastapi import WebSocket

log = logging.getLogger("gnani")

URL = os.environ.get("GNANI_STT_URL", "wss://api.vachana.ai/stt/v3/stream")
SAMPLE_RATE = 16000
FRAME = 1024                 # Gnani wants exactly 512 samples (32 ms) per binary frame
MAX_QUEUE = 150              # ~5 s of audio; older frames are dropped if Gnani falls behind
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env() -> None:
    """Read backend/.env without overriding variables that are already set."""
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def api_key() -> str:
    return os.environ.get("GNANI_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key()) and os.environ.get("CAPTIONS_ENGINE", "gnani") != "browser"


def headers() -> dict[str, str]:
    return {
        "x-api-key-id": api_key(),
        "model": "prisma-v3.0",
        # indic-auto detects the language per sentence (English, Hindi, Tamil...). Streaming
        # rejects a list like "en-IN,hi-IN" despite the docs; use one code to pin a language.
        "language_code": os.environ.get("GNANI_LANGUAGE", "indic-auto"),
        # English words stay in Latin script inside Hindi sentences (Hinglish).
        "format": os.environ.get("GNANI_FORMAT", "codemix"),
        "x-sample-rate": str(SAMPLE_RATE),
        "x-idle-timeout-sec": "900",          # a speaker may pause for a while
        "x-max-speech-s": "12",               # someone who never pauses still gets lines
        "x-partials": "true",                 # words as they are spoken
    }


OnText = Callable[[str], Awaitable[None]]
OnError = Callable[[str], Awaitable[None]]


async def relay(browser: WebSocket, on_partial: OnText, on_text: OnText, on_error: OnError) -> None:
    """Forward the browser's audio to Gnani until the browser disconnects."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def from_browser() -> None:
        buf = bytearray()
        try:
            while True:
                msg = await browser.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                data = msg.get("bytes")
                if data:
                    buf += data
                    while len(buf) >= FRAME:
                        if queue.qsize() < MAX_QUEUE:
                            queue.put_nowait(bytes(buf[:FRAME]))
                        del buf[:FRAME]
                elif msg.get("text") and json.loads(msg["text"]).get("type") == "stop":
                    break
        except Exception:                 # noqa: BLE001  browser went away
            pass
        finally:
            queue.put_nowait(None)

    reader = asyncio.create_task(from_browser())
    failures = 0
    try:
        while True:
            finished = await _session(queue, on_partial, on_text)
            if finished:
                return
            failures += 1
            if failures > 5:
                await on_error("Lost the connection to Gnani. Stop and start captioning again.")
                return
            await asyncio.sleep(min(2 ** failures, 10) * 0.5)
    except _Fatal as e:
        await on_error(str(e))
    finally:
        reader.cancel()


class _Fatal(Exception):
    """An error retrying won't fix (bad key, bad settings)."""


async def _session(queue: asyncio.Queue, on_partial: OnText, on_text: OnText) -> bool:
    """One Gnani connection. True when the browser has finished, False to reconnect."""
    try:
        conn = await websockets.connect(URL, additional_headers=headers(), open_timeout=10,
                                        ping_interval=20, max_size=2 ** 20)
    except websockets.InvalidStatus as e:
        code = e.response.status_code
        if code in (401, 403):
            raise _Fatal("Gnani rejected the API key (check GNANI_API_KEY in backend/.env).") from e
        log.warning("gnani handshake failed: %s", code)
        return False
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
        log.warning("gnani connect failed: %s", e)
        return False

    browser_done = asyncio.Event()

    async def send() -> None:
        while True:
            frame = await queue.get()
            if frame is None:
                browser_done.set()
                await conn.send(json.dumps({"type": "commit"}))   # finish the last sentence
                return
            await conn.send(frame)

    async def recv() -> None:
        async for raw in conn:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "partial_transcript":
                await on_partial(" ".join(str(msg.get("text", "")).split()))
            elif kind in ("final_transcript", "transcript"):
                await on_text(" ".join(str(msg.get("text", "")).split()))
            elif kind == "error":
                text = str(msg.get("message", "unknown error"))
                log.warning("gnani error: %s", text)
                if any(w in text.lower() for w in ("language", "format", "invalid")):
                    raise _Fatal(f"Gnani: {text}")

    sender, receiver = asyncio.create_task(send()), asyncio.create_task(recv())
    try:
        await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        if receiver.done() and receiver.exception():
            exc = receiver.exception()
            if isinstance(exc, _Fatal):
                raise exc
        if browser_done.is_set():
            try:                              # give Gnani a moment to send the last line
                await asyncio.wait_for(asyncio.shield(receiver), 3)
            except (asyncio.TimeoutError, Exception):   # noqa: BLE001
                pass
            return True
        return False                          # Gnani closed (15 min limit, network): reconnect
    finally:
        sender.cancel()
        receiver.cancel()
        await conn.close()
