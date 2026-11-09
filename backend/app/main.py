"""Live captions for in-person events, with questions from the audience.

Speaker (laptop):
  POST   /api/events                      start an event        -> code, speaker token
  WS     /ws/events/{code}/speak?token=   send captions: {"type":"partial"|"final","text"}
                                          answer a question: {"type":"answer","question_id": 3}
                                          ... speak ... then {"type":"answer","question_id": null}
                                          receive: questions, listener count
  PATCH  /api/events/{code}/questions/{id}  mark a question answered   (x-token header)
  POST   /api/events/{code}/questions/{id}/block  block the phone that asked it (x-token)
  DELETE /api/events/{code}               end the event              (x-token header)
  GET    /api/events/{code}/qr.svg        QR code for the screen

Attendee (phone, no sign-up):
  GET    /api/events/{code}               event title, live or not
  WS     /ws/events/{code}/listen         receive: recent captions, then live ones
  POST   /api/events/{code}/questions     ask a question {"text", "name"?, "client_id"}
"""
from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .events import QUESTION_EVERY_S, QUESTION_MAX, Event, store

app = FastAPI(title="Live Captions API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
# The address phones should open (a tunnel or the laptop's Wi-Fi address). demo.sh writes it
# to this file once the tunnel is up, so it can change without restarting the server.
PUBLIC_URL_FILE = Path(__file__).resolve().parents[2] / ".public_url"


def public_url() -> str | None:
    url = os.environ.get("PUBLIC_URL")
    if not url and PUBLIC_URL_FILE.exists():
        url = PUBLIC_URL_FILE.read_text().strip()
    return url.rstrip("/") if url else None


def join_url(code: str, base: str | None = None) -> str:
    return f"{(base or public_url() or FRONTEND_URL).rstrip('/')}/e/{code}"


def _safe_base(base: str | None) -> str | None:
    """Only plain http(s) origins, e.g. https://192.168.1.5:5173."""
    if not base:
        return None
    u = urlparse(base)
    if u.scheme not in ("http", "https") or not u.netloc or u.path not in ("", "/") or u.query:
        raise HTTPException(400, "base must be an http(s) origin like https://192.168.1.5:5173")
    return f"{u.scheme}://{u.netloc}"


def _event(code: str) -> Event:
    ev = store.get(code)
    if not ev:
        raise HTTPException(404, "Event not found or it has ended")
    return ev


def _speaker(ev: Event, token: str | None) -> None:
    if not token or token != ev.token:
        raise HTTPException(403, "Only the speaker can do this")


@app.get("/api/health")
def health():
    return {"ok": True, "events": len(store.events)}


@app.get("/api/config")
def config():
    """Where phones should go. None means only this laptop can open the app."""
    return {"phone_url": public_url()}


# --------------------------------------------------------------------------- #
#  Speaker
# --------------------------------------------------------------------------- #
class StartEvent(BaseModel):
    title: str = Field("", max_length=80)


@app.post("/api/events")
def start_event(req: StartEvent):
    ev = store.create(req.title)
    return {"code": ev.code, "title": ev.title, "token": ev.token, "join_url": join_url(ev.code)}


@app.get("/api/events/{code}/qr.svg")
def event_qr(code: str, base: Optional[str] = None):
    import segno
    ev = _event(code)
    buf = io.BytesIO()
    segno.make(join_url(ev.code, _safe_base(base)), error="m").save(buf, kind="svg", scale=10,
                                                                  border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml")


class MarkQuestion(BaseModel):
    answered: bool


@app.patch("/api/events/{code}/questions/{qid}")
async def mark_question(code: str, qid: int, req: MarkQuestion, x_token: Optional[str] = Header(None)):
    ev = _event(code)
    _speaker(ev, x_token)
    q = next((q for q in ev.questions if q.id == qid), None)
    if not q:
        raise HTTPException(404, "No such question")
    q.answered = req.answered
    await ev.to_speaker({"type": "question_update", "question": q.model_dump()})
    return q


@app.post("/api/events/{code}/questions/{qid}/block")
async def block_asker(code: str, qid: int, x_token: Optional[str] = Header(None)):
    """Stop the phone that sent this question from sending more, and remove its questions.

    The blocked phone isn't told: its questions still look "sent" on its screen, so a
    troll has no reason to clear their browser and come back with a new id.
    """
    ev = _event(code)
    _speaker(ev, x_token)
    was_answering = ev.answering
    gone = ev.block(qid)
    if gone is None:
        raise HTTPException(404, "No such question")
    await ev.to_speaker({"type": "questions_removed", "ids": gone})
    if was_answering and not ev.answering:
        await ev.everyone({"type": "answering", "question": None})
    return {"ok": True, "removed": gone}


@app.delete("/api/events/{code}")
async def end_event(code: str, x_token: Optional[str] = Header(None)):
    ev = _event(code)
    _speaker(ev, x_token)
    store.delete(ev.code)
    await ev.everyone({"type": "ended"})
    await ev.close_all()
    return {"ok": True}


@app.websocket("/ws/events/{code}/speak")
async def speak(ws: WebSocket, code: str, token: str = ""):
    ev = store.get(code)
    await ws.accept()
    if not ev or token != ev.token:
        await ws.send_json({"type": "error", "error": "Event not found or wrong speaker token"})
        await ws.close(code=4403)
        return
    ev.speakers.add(ws)
    await ws.send_json({"type": "state", "event": ev.info(),
                        "captions": [c.model_dump() for c in ev.captions],
                        "questions": [q.model_dump() for q in ev.questions],
                        "answering": _ref(ev)})
    await ev.to_listeners({"type": "live", "live": True})
    try:
        while True:
            data = await ws.receive_json()
            if store.get(code) is not ev or not isinstance(data, dict):
                break
            text = " ".join(str(data.get("text", "")).split())[:1000]
            if data.get("type") == "partial":
                ev.partial = text
                await ev.to_listeners({"type": "partial", "text": text})
            elif data.get("type") == "final" and text:
                c = ev.add_caption(text)
                await ev.everyone({"type": "caption", "caption": c.model_dump()})
            elif data.get("type") == "answer":
                await _answer(ev, data.get("question_id"))
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        ev.speakers.discard(ws)
        if store.get(code) is ev and not ev.speakers:
            ev.partial = ""
            await ev.to_listeners({"type": "live", "live": False})


def _ref(ev: Event) -> dict | None:
    ref = ev.answering_ref()
    return ref.model_dump() if ref else None


async def _answer(ev: Event, question_id) -> None:
    """Start answering a question out loud (captions get linked to it), or finish (None)."""
    if question_id is None:
        q = ev.finish_answering()
        if q:
            await ev.to_speaker({"type": "question_update", "question": q.model_dump()})
            await ev.everyone({"type": "answering", "question": None})
        return
    if not isinstance(question_id, int) or not ev.start_answering(question_id):
        await ev.to_speaker({"type": "notice", "text": "That question is no longer there."})
        return
    await ev.everyone({"type": "answering", "question": _ref(ev)})


# --------------------------------------------------------------------------- #
#  Attendees
# --------------------------------------------------------------------------- #
@app.get("/api/events/{code}")
def event_info(code: str):
    return _event(code).info()


class Ask(BaseModel):
    text: str = Field(..., min_length=1, max_length=QUESTION_MAX)
    name: Optional[str] = Field(None, max_length=40)
    client_id: str = Field(..., min_length=4, max_length=64)   # random id kept on the phone


@app.post("/api/events/{code}/questions")
async def ask(code: str, req: Ask):
    ev = _event(code)
    text = " ".join(req.text.split())
    if not text:
        raise HTTPException(422, "Question is empty")
    if req.client_id in ev.blocked:
        return {"ok": True, "id": None}     # quietly dropped (see block_asker)
    now = time.time()
    if now - ev.last_question.get(req.client_id, 0) < QUESTION_EVERY_S:
        raise HTTPException(429, "Please wait a few seconds before asking again")
    ev.last_question[req.client_id] = now
    q = ev.add_question(text, (req.name or "").strip() or None, req.client_id)
    await ev.to_speaker({"type": "question", "question": q.model_dump()})
    return {"ok": True, "id": q.id}


async def _count(ev: Event) -> None:
    await ev.to_speaker({"type": "listeners", "count": len(ev.listeners)})


@app.websocket("/ws/events/{code}/listen")
async def listen(ws: WebSocket, code: str):
    ev = store.get(code)
    await ws.accept()
    if not ev:
        await ws.send_json({"type": "error", "error": "Event not found or it has ended"})
        await ws.close(code=4404)
        return
    ev.listeners.add(ws)
    await ws.send_json({"type": "state", "event": ev.info(),
                        "captions": [c.model_dump() for c in ev.captions[-50:]],
                        "partial": ev.partial, "answering": _ref(ev)})
    await _count(ev)
    try:
        while True:                     # attendees only listen; this just notices them leave
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        ev.listeners.discard(ws)
        if store.get(code) is ev:
            await _count(ev)
