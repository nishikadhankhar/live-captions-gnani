"""Events, captions and questions. Everything lives in memory: no database, no accounts.

An event is started by the speaker (or organiser). Attendees open it by scanning a QR
code: they get the live captions and can send the speaker a question. That's all.
"""
from __future__ import annotations

import asyncio
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket
from pydantic import BaseModel, Field

IDLE_EXPIRY_S = 6 * 3600          # an event nobody touched for 6 hours is deleted
HISTORY = 200                     # captions a late arrival can scroll back through
SEND_TIMEOUT_S = 3                # a phone on bad Wi-Fi must not hold up everyone else
QUESTION_MAX = 300
QUESTION_EVERY_S = 5              # per attendee, against spam
CODE_CHARS = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")


class QuestionRef(BaseModel):
    """What attendees see of a question being answered (never who sent it from which phone)."""
    id: int
    text: str
    name: Optional[str] = None


class Caption(BaseModel):
    id: int
    text: str
    at: float
    answer_to: Optional[QuestionRef] = None     # set while the speaker is answering a question


class Question(BaseModel):
    id: int
    text: str
    name: Optional[str] = None
    at: float
    answered: bool = False
    # Which phone asked (a random id, no identity). Kept on the server only, for blocking.
    client_id: str = Field("", exclude=True)


@dataclass
class Event:
    code: str
    title: str
    token: str                                        # the speaker's secret
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    captions: list[Caption] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    speakers: set[WebSocket] = field(default_factory=set)
    listeners: set[WebSocket] = field(default_factory=set)
    last_question: dict[str, float] = field(default_factory=dict)   # attendee id -> time
    blocked: set[str] = field(default_factory=set)                   # attendee ids
    partial: str = ""                                 # words being spoken right now
    answering: Optional[Question] = None              # the question the speaker is answering
    _next_caption: int = 1
    _next_question: int = 1

    def touch(self) -> None:
        self.last_active = time.time()

    def add_caption(self, text: str) -> Caption:
        c = Caption(id=self._next_caption, text=text, at=time.time(), answer_to=self.answering_ref())
        self._next_caption += 1
        self.captions.append(c)
        del self.captions[:-HISTORY]
        self.partial = ""
        self.touch()
        return c

    def add_question(self, text: str, name: str | None, client_id: str = "") -> Question:
        q = Question(id=self._next_question, text=text, name=name, at=time.time(),
                     client_id=client_id)
        self._next_question += 1
        self.questions.append(q)
        self.touch()
        return q

    def answering_ref(self) -> QuestionRef | None:
        a = self.answering
        return QuestionRef(id=a.id, text=a.text, name=a.name) if a else None

    def start_answering(self, question_id: int) -> Question | None:
        q = next((q for q in self.questions if q.id == question_id), None)
        if q:
            self.answering = q
            self.touch()
        return q

    def finish_answering(self) -> Question | None:
        """The speaker tapped Done: the question counts as answered."""
        q, self.answering = self.answering, None
        if q:
            q.answered = True
            self.touch()
        return q

    def block(self, question_id: int) -> list[int] | None:
        """Block the phone that sent this question. Removes all its questions; returns their ids."""
        q = next((q for q in self.questions if q.id == question_id), None)
        if not q:
            return None
        if q.client_id:
            self.blocked.add(q.client_id)
        gone = [x.id for x in self.questions if x.id == q.id or (q.client_id and x.client_id == q.client_id)]
        self.questions = [x for x in self.questions if x.id not in gone]
        if self.answering and self.answering.id in gone:
            self.answering = None
        self.touch()
        return gone

    def info(self) -> dict:
        return {"code": self.code, "title": self.title, "live": bool(self.speakers),
                "listeners": len(self.listeners)}

    # ----------------------------------------------------------------- sending
    async def _send(self, ws: WebSocket, event: dict) -> bool:
        """False only if the socket is gone. A slow phone just misses this one event."""
        try:
            await asyncio.wait_for(ws.send_json(event), timeout=SEND_TIMEOUT_S)
            return True
        except asyncio.TimeoutError:
            return True
        except Exception:               # noqa: BLE001
            return False

    async def _send_all(self, group: set[WebSocket], event: dict) -> None:
        socks = list(group)
        results = await asyncio.gather(*(self._send(ws, event) for ws in socks))
        for ws, ok in zip(socks, results):
            if not ok:
                group.discard(ws)

    async def to_listeners(self, event: dict) -> None:
        await self._send_all(self.listeners, event)

    async def to_speaker(self, event: dict) -> None:
        await self._send_all(self.speakers, event)

    async def everyone(self, event: dict) -> None:
        await asyncio.gather(self.to_listeners(event), self.to_speaker(event))

    async def close_all(self) -> None:
        async def close(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.close(), timeout=1)
            except Exception:           # noqa: BLE001
                pass
        await asyncio.gather(*(close(ws) for ws in [*self.speakers, *self.listeners]))


class EventStore:
    def __init__(self) -> None:
        self.events: dict[str, Event] = {}

    def create(self, title: str) -> Event:
        self.expire()
        while True:
            code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
            if code not in self.events:
                break
        ev = Event(code=code, title=title.strip()[:80], token=secrets.token_urlsafe(16))
        self.events[code] = ev
        return ev

    def get(self, code: str) -> Event | None:
        return self.events.get(code.strip().upper())

    def delete(self, code: str) -> None:
        self.events.pop(code.strip().upper(), None)

    def expire(self, now: float | None = None) -> int:
        now = now or time.time()
        old = [c for c, e in self.events.items()
               if now - e.last_active > IDLE_EXPIRY_S and not e.speakers]
        for c in old:
            del self.events[c]
        return len(old)


store = EventStore()
