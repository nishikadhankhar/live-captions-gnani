"""Tests for live captions + audience questions.

REST calls use FastAPI's TestClient. Live (WebSocket) tests talk to a real uvicorn server in
a background thread: TestClient runs every WebSocket on its own event loop, which a real
server never does, so it can't test a speaker and many phones together.

    python3 -m pytest tests/ -q --timeout 20
"""
import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient

import app.main as main
from app.events import HISTORY, IDLE_EXPIRY_S, EventStore
from app.main import app, store

client = TestClient(app)


def start(title="Accessibility in Tech"):
    return client.post("/api/events", json={"title": title}).json()


# --------------------------------------------------------------------------- #
#  REST
# --------------------------------------------------------------------------- #
class TestEvents:
    def test_start_event(self):
        ev = start()
        assert len(ev["code"]) == 5 and ev["token"] and ev["title"] == "Accessibility in Tech"
        assert ev["join_url"].endswith(f"/e/{ev['code']}")

    def test_title_is_optional(self):
        assert client.post("/api/events", json={}).status_code == 200

    def test_attendee_sees_info_but_not_the_token(self):
        ev = start()
        info = client.get(f"/api/events/{ev['code'].lower()}").json()   # code is case-insensitive
        assert info == {"code": ev["code"], "title": "Accessibility in Tech", "live": False,
                        "listeners": 0}

    def test_unknown_event_is_404(self):
        assert client.get("/api/events/ZZZZZ").status_code == 404

    def test_qr_code(self):
        ev = start()
        r = client.get(f"/api/events/{ev['code']}/qr.svg", params={"base": "https://10.0.0.5:5174"})
        assert r.status_code == 200 and b"<svg" in r.content
        for bad in ("javascript:alert(1)", "https://x.com/a?b=1", "ftp://x"):
            assert client.get(f"/api/events/{ev['code']}/qr.svg", params={"base": bad}).status_code == 400

    def test_phone_url_from_tunnel(self, monkeypatch):
        monkeypatch.setattr(main, "PUBLIC_URL_FILE", main.Path("/nonexistent"))
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        assert client.get("/api/config").json()["phone_url"] is None
        monkeypatch.setenv("PUBLIC_URL", "https://abc.trycloudflare.com/")
        assert client.get("/api/config").json()["phone_url"] == "https://abc.trycloudflare.com"
        assert start()["join_url"].startswith("https://abc.trycloudflare.com/e/")

    def test_only_speaker_can_end(self):
        ev = start()
        url = f"/api/events/{ev['code']}"
        assert client.delete(url).status_code == 403
        assert client.delete(url, headers={"x-token": "wrong"}).status_code == 403
        assert client.delete(url, headers={"x-token": ev["token"]}).status_code == 200
        assert client.get(url).status_code == 404


class TestQuestions:
    def test_ask(self):
        ev = start()
        r = client.post(f"/api/events/{ev['code']}/questions",
                        json={"text": "  Will the slides be shared? ", "client_id": "phone-1"})
        assert r.status_code == 200
        q = store.get(ev["code"]).questions[0]
        assert q.text == "Will the slides be shared?" and q.name is None and not q.answered

    def test_name_is_optional_and_trimmed(self):
        ev = start()
        client.post(f"/api/events/{ev['code']}/questions",
                    json={"text": "Hi", "name": "  Priya ", "client_id": "phone-1"})
        assert store.get(ev["code"]).questions[0].name == "Priya"

    def test_empty_or_too_long_rejected(self):
        ev = start()
        url = f"/api/events/{ev['code']}/questions"
        assert client.post(url, json={"text": "", "client_id": "phone-1"}).status_code == 422
        assert client.post(url, json={"text": "   ", "client_id": "phone-1"}).status_code == 422
        assert client.post(url, json={"text": "x" * 301, "client_id": "phone-1"}).status_code == 422

    def test_spam_is_slowed_down(self):
        ev = start()
        url = f"/api/events/{ev['code']}/questions"
        assert client.post(url, json={"text": "one", "client_id": "phone-1"}).status_code == 200
        assert client.post(url, json={"text": "two", "client_id": "phone-1"}).status_code == 429
        assert client.post(url, json={"text": "two", "client_id": "phone-2"}).status_code == 200

    def test_speaker_marks_answered(self):
        ev = start()
        client.post(f"/api/events/{ev['code']}/questions", json={"text": "Q?", "client_id": "phone-1"})
        url = f"/api/events/{ev['code']}/questions/1"
        assert client.patch(url, json={"answered": True}).status_code == 403
        r = client.patch(url, json={"answered": True}, headers={"x-token": ev["token"]})
        assert r.status_code == 200 and r.json()["answered"] is True
        assert client.patch(f"/api/events/{ev['code']}/questions/99", json={"answered": True},
                            headers={"x-token": ev["token"]}).status_code == 404


class TestBlocking:
    def _ask(self, code, text, phone):
        return client.post(f"/api/events/{code}/questions", json={"text": text, "client_id": phone})

    def test_block_removes_all_their_questions_and_stops_new_ones(self):
        ev = start()
        code, h = ev["code"], {"x-token": ev["token"]}
        self._ask(code, "How are you babe", "troll-phone")
        self._ask(code, "Will slides be shared?", "good-phone")
        store.get(code).last_question.clear()
        self._ask(code, "more garbage", "troll-phone")
        r = client.post(f"/api/events/{code}/questions/1/block", headers=h)
        assert r.status_code == 200 and sorted(r.json()["removed"]) == [1, 3]
        assert [q.text for q in store.get(code).questions] == ["Will slides be shared?"]
        # The blocked phone is told "ok" but nothing reaches the speaker.
        store.get(code).last_question.clear()
        r = self._ask(code, "trying again", "troll-phone")
        assert r.status_code == 200 and r.json()["id"] is None
        assert len(store.get(code).questions) == 1
        # Everyone else can still ask.
        assert self._ask(code, "Another real question", "other-phone").json()["id"] is not None

    def test_only_speaker_can_block(self):
        ev = start()
        self._ask(ev["code"], "rude", "troll-phone")
        url = f"/api/events/{ev['code']}/questions/1/block"
        assert client.post(url).status_code == 403
        assert client.post(url, headers={"x-token": "wrong"}).status_code == 403
        assert client.post(f"/api/events/{ev['code']}/questions/9/block",
                           headers={"x-token": ev["token"]}).status_code == 404

    def test_phone_id_is_never_shown_to_the_speaker(self):
        ev = start()
        self._ask(ev["code"], "hello", "secret-phone-id")
        dumped = store.get(ev["code"]).questions[0].model_dump()
        assert "client_id" not in dumped and "secret-phone-id" not in str(dumped)


class TestStore:
    def test_codes_avoid_confusable_characters(self):
        s = EventStore()
        for _ in range(50):
            assert not set(s.create("").code) & set("0O1IL")

    def test_idle_events_expire(self):
        s = EventStore()
        ev = s.create("")
        assert s.expire(now=ev.last_active + IDLE_EXPIRY_S + 1) == 1 and s.get(ev.code) is None

    def test_caption_history_is_capped(self):
        ev = EventStore().create("")
        for i in range(HISTORY + 20):
            ev.add_caption(f"line {i}")
        assert len(ev.captions) == HISTORY and ev.captions[-1].text == f"line {HISTORY + 19}"


# --------------------------------------------------------------------------- #
#  Live, against a real server
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(url + "/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield url
    srv.should_exit = True


class Socket:
    """A WebSocket that remembers every event it received."""

    def __init__(self, url: str):
        self.url, self.events = url, []

    async def __aenter__(self):
        self.ws = await websockets.connect(self.url)
        return self

    async def __aexit__(self, *exc):
        await self.ws.close()

    async def send(self, **event):
        await self.ws.send(json.dumps(event))

    async def wait(self, kind: str, timeout: float = 3) -> dict:
        for ev in self.events:
            if ev["type"] == kind and not ev.get("_used"):
                ev["_used"] = True
                return ev
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = json.loads(await asyncio.wait_for(self.ws.recv(), end - time.time()))
            except asyncio.TimeoutError:
                break
            self.events.append(ev)
            if ev["type"] == kind:
                ev["_used"] = True
                return ev
        raise AssertionError(f"never got a '{kind}' event")


def ws(server: str, path: str) -> str:
    return server.replace("http", "ws", 1) + path


def run(coro):
    return asyncio.run(coro)


class TestLive:
    def test_wrong_speaker_token_rejected(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        async def go():
            async with Socket(ws(server, f"/ws/events/{ev['code']}/speak?token=bad")) as s:
                assert (await s.wait("error"))["error"]
        run(go())

    def test_listening_to_unknown_event(self, server):
        async def go():
            async with Socket(ws(server, "/ws/events/ZZZZZ/listen")) as s:
                assert await s.wait("error")
        run(go())

    def test_captions_reach_every_phone_live(self, server):
        ev = httpx.post(server + "/api/events", json={"title": "Talk"}).json()
        code = ev["code"]
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")) as sp, \
                       Socket(ws(server, f"/ws/events/{code}/listen")) as a, \
                       Socket(ws(server, f"/ws/events/{code}/listen")) as b:
                await sp.wait("state")
                st = await a.wait("state")
                assert st["event"]["title"] == "Talk" and st["event"]["live"] is True
                await sp.send(type="partial", text="hello my name")
                assert (await a.wait("partial"))["text"] == "hello my name"
                assert (await b.wait("partial"))["text"] == "hello my name"
                await sp.send(type="final", text="Hello, my name is Astha Malik")
                for phone in (a, b):
                    c = (await phone.wait("caption"))["caption"]
                    assert c["text"] == "Hello, my name is Astha Malik" and c["id"] == 1
                assert (await sp.wait("caption"))["caption"]["id"] == 1   # speaker sees it too
        run(go())

    def test_late_arrival_gets_recent_captions_and_live_words(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")) as sp:
                await sp.wait("state")
                await sp.send(type="final", text="first line")
                await sp.send(type="final", text="second line")
                await sp.send(type="partial", text="third li")
                await sp.wait("caption"); await sp.wait("caption")
                await asyncio.sleep(0.1)
                async with Socket(ws(server, f"/ws/events/{code}/listen")) as late:
                    st = await late.wait("state")
                    assert [c["text"] for c in st["captions"]] == ["first line", "second line"]
                    assert st["partial"] == "third li"
        run(go())

    def test_speaker_sees_questions_and_listener_count(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")) as sp:
                await sp.wait("state")
                async with Socket(ws(server, f"/ws/events/{code}/listen")) as a:
                    await a.wait("state")
                    assert (await sp.wait("listeners"))["count"] == 1
                    await asyncio.to_thread(httpx.post, f"{server}/api/events/{code}/questions",
                                            json={"text": "Can you repeat that?", "client_id": "phone-1"})
                    q = (await sp.wait("question"))["question"]
                    assert q["text"] == "Can you repeat that?" and q["id"] == 1
                    with pytest.raises(AssertionError):     # questions never go to attendees
                        await a.wait("question", timeout=0.5)
                assert (await sp.wait("listeners"))["count"] == 0
        run(go())

    def test_speaker_screen_drops_blocked_questions_live(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")) as sp:
                await sp.wait("state")
                await asyncio.to_thread(httpx.post, f"{server}/api/events/{code}/questions",
                                        json={"text": "rude", "client_id": "troll-phone"})
                q = (await sp.wait("question"))["question"]
                assert "client_id" not in q
                await asyncio.to_thread(httpx.post, f"{server}/api/events/{code}/questions/{q['id']}/block",
                                        headers={"x-token": ev["token"]})
                assert (await sp.wait("questions_removed"))["ids"] == [q["id"]]
        run(go())

    def test_answering_a_question_out_loud(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        httpx.post(f"{server}/api/events/{code}/questions",
                   json={"text": "Will slides be shared?", "name": "Priya", "client_id": "phone-1"})
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")) as sp, \
                       Socket(ws(server, f"/ws/events/{code}/listen")) as a:
                await sp.wait("state"); await a.wait("state")
                await sp.send(type="final", text="Before the questions, one more slide.")
                assert (await a.wait("caption"))["caption"]["answer_to"] is None

                await sp.send(type="answer", question_id=1)          # tap "Answer"
                q = (await a.wait("answering"))["question"]
                assert q == {"id": 1, "text": "Will slides be shared?", "name": "Priya"}
                await sp.send(type="final", text="Yes, I'll share them after the talk.")
                c = (await a.wait("caption"))["caption"]
                assert c["answer_to"]["id"] == 1 and "client_id" not in str(c)

                # someone joining now sees which question is being answered
                async with Socket(ws(server, f"/ws/events/{code}/listen")) as late:
                    st = await late.wait("state")
                    assert st["answering"]["id"] == 1
                    assert st["captions"][-1]["answer_to"]["text"] == "Will slides be shared?"

                await sp.send(type="answer", question_id=None)       # tap "Done"
                assert (await a.wait("answering"))["question"] is None
                upd = (await sp.wait("question_update"))["question"]
                assert upd["id"] == 1 and upd["answered"] is True
                await sp.send(type="final", text="Moving on.")
                assert (await a.wait("caption"))["caption"]["answer_to"] is None
        run(go())

    def test_answering_a_missing_question_is_refused(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        async def go():
            async with Socket(ws(server, f"/ws/events/{ev['code']}/speak?token={ev['token']}")) as sp:
                await sp.wait("state")
                await sp.send(type="answer", question_id=42)
                assert await sp.wait("notice")
        run(go())

    def test_blocking_the_question_being_answered_stops_answering(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        httpx.post(f"{server}/api/events/{code}/questions", json={"text": "rude", "client_id": "troll-phone"})
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")) as sp, \
                       Socket(ws(server, f"/ws/events/{code}/listen")) as a:
                await sp.wait("state"); await a.wait("state")
                await sp.send(type="answer", question_id=1)
                await a.wait("answering")
                await asyncio.to_thread(httpx.post, f"{server}/api/events/{code}/questions/1/block",
                                        headers={"x-token": ev["token"]})
                assert (await a.wait("answering"))["question"] is None
        run(go())

    def test_attendees_see_when_speaker_is_live(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/listen")) as a:
                assert (await a.wait("state"))["event"]["live"] is False
                async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")):
                    assert (await a.wait("live"))["live"] is True
                assert (await a.wait("live"))["live"] is False
        run(go())

    def test_ending_tells_everyone_and_is_quick(self, server):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/listen")) as a:
                await a.wait("state")
                # A phone that connected and then stopped reading (locked screen).
                stuck = await websockets.connect(ws(server, f"/ws/events/{code}/listen"))
                t0 = time.time()
                r = await asyncio.to_thread(httpx.delete, f"{server}/api/events/{code}",
                                            headers={"x-token": ev["token"]})
                assert r.status_code == 200 and time.time() - t0 < 3
                assert await a.wait("ended")
                await stuck.close()
        run(go())


# --------------------------------------------------------------------------- #
#  Captions from Gnani (against a fake Gnani server: no API credit, works offline)
# --------------------------------------------------------------------------- #
class FakeGnani:
    """Speaks Gnani's streaming protocol: a partial every 10 frames, a final line on commit."""

    def __init__(self):
        self.headers: dict = {}
        self.bad_frames = 0
        self.frames = 0

    async def handler(self, conn):
        h = conn.request.headers
        self.headers = dict(h)
        if h.get("language_code") == "xx-IN":
            await conn.send(json.dumps({"type": "error", "message": "Invalid language_code: xx-IN"}))
            await conn.close(1008)
            return
        await conn.send(json.dumps({"type": "connected", "config": {"sample_rate": 16000}}))
        words = ["namaste", "everyone", "welcome"]
        async for msg in conn:
            if isinstance(msg, bytes):
                self.frames += 1
                self.bad_frames += len(msg) != 1024
                if self.frames % 10 == 0:
                    text = " ".join(words[: min(self.frames // 10, 3)])
                    await conn.send(json.dumps({"type": "partial_transcript", "text": text}))
            elif json.loads(msg).get("type") == "commit":
                await conn.send(json.dumps({"type": "final_transcript", "text": "Namaste everyone, welcome."}))

    @staticmethod
    def reject_bad_key(conn, request):
        if request.headers.get("x-api-key-id") == "bad":
            return conn.respond(401, "Unauthorized")


@pytest.fixture(scope="module")
def fake_gnani():
    from websockets.asyncio.server import serve

    fake = FakeGnani()
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    box = {}

    async def main():
        async with serve(fake.handler, "127.0.0.1", 0, process_request=FakeGnani.reject_bad_key) as srv:
            box["port"] = srv.sockets[0].getsockname()[1]
            ready.set()
            await asyncio.Future()

    threading.Thread(target=lambda: loop.run_until_complete(main()), daemon=True).start()
    ready.wait(5)
    fake.url = f"ws://127.0.0.1:{box['port']}"
    yield fake
    loop.call_soon_threadsafe(loop.stop)


@pytest.fixture
def use_gnani(fake_gnani, monkeypatch):
    from app import gnani
    monkeypatch.setattr(gnani, "URL", fake_gnani.url)
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    monkeypatch.delenv("GNANI_LANGUAGE", raising=False)
    monkeypatch.delenv("CAPTIONS_ENGINE", raising=False)
    return fake_gnani


async def speak_audio(server, code, token, frames=35, chunk=4096):
    """Act like the browser mic: send 16 kHz PCM in uneven blocks, then stop."""
    audio = bytes(frames * 1024)
    async with Socket(ws(server, f"/ws/events/{code}/audio?token={token}")) as mic:
        assert await mic.wait("ready")
        for i in range(0, len(audio), chunk):
            await mic.ws.send(audio[i:i + chunk])
            await asyncio.sleep(0.01)
        await mic.send(type="stop")
        await asyncio.sleep(0.5)


class TestGnani:
    def test_config_says_which_engine(self, monkeypatch):
        monkeypatch.setenv("GNANI_API_KEY", "k")
        monkeypatch.delenv("CAPTIONS_ENGINE", raising=False)
        assert client.get("/api/config").json()["stt"] == "gnani"
        monkeypatch.setenv("CAPTIONS_ENGINE", "browser")      # force Chrome's recognition
        assert client.get("/api/config").json()["stt"] == "browser"
        monkeypatch.delenv("CAPTIONS_ENGINE")
        monkeypatch.setenv("GNANI_API_KEY", "")
        assert client.get("/api/config").json()["stt"] == "browser"

    def test_audio_becomes_captions_on_every_phone(self, server, use_gnani):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/listen")) as phone:
                await phone.wait("state")
                await speak_audio(server, code, ev["token"])
                assert (await phone.wait("partial"))["text"] == "namaste"
                cap = (await phone.wait("caption", timeout=5))["caption"]
                assert cap["text"] == "Namaste everyone, welcome."
        run(go())
        h = use_gnani.headers
        assert h["x-api-key-id"] == "test-key" and h["model"] == "prisma-v3.0"
        assert h["language_code"] == "indic-auto" and h["x-sample-rate"] == "16000"
        assert h["x-partials"] == "true"
        assert use_gnani.bad_frames == 0                       # re-framed to exactly 1024 bytes

    def test_captions_link_to_the_question_being_answered(self, server, use_gnani):
        ev = httpx.post(server + "/api/events", json={}).json()
        code = ev["code"]
        q = httpx.post(f"{server}/api/events/{code}/questions",
                       json={"text": "Is it free?", "client_id": "phone-1"}).json()
        async def go():
            async with Socket(ws(server, f"/ws/events/{code}/speak?token={ev['token']}")) as sp, \
                       Socket(ws(server, f"/ws/events/{code}/listen")) as phone:
                await sp.wait("state")
                await sp.send(type="answer", question_id=q["id"])
                await phone.wait("answering")
                await speak_audio(server, code, ev["token"], frames=12)
                cap = (await phone.wait("caption", timeout=5))["caption"]
                assert cap["answer_to"]["text"] == "Is it free?"
        run(go())

    def test_only_the_speaker_can_send_audio(self, server, use_gnani):
        ev = httpx.post(server + "/api/events", json={}).json()
        async def go():
            async with Socket(ws(server, f"/ws/events/{ev['code']}/audio?token=bad")) as mic:
                assert "token" in (await mic.wait("error"))["error"]
        run(go())

    def test_bad_key_is_reported_to_the_speaker(self, server, use_gnani, monkeypatch):
        monkeypatch.setenv("GNANI_API_KEY", "bad")
        ev = httpx.post(server + "/api/events", json={}).json()
        async def go():
            async with Socket(ws(server, f"/ws/events/{ev['code']}/audio?token={ev['token']}")) as mic:
                await mic.wait("ready")
                await mic.ws.send(bytes(4096))
                assert "API key" in (await mic.wait("error", timeout=5))["error"]
        run(go())

    def test_bad_language_is_reported_not_retried(self, server, use_gnani, monkeypatch):
        monkeypatch.setenv("GNANI_LANGUAGE", "xx-IN")
        ev = httpx.post(server + "/api/events", json={}).json()
        async def go():
            async with Socket(ws(server, f"/ws/events/{ev['code']}/audio?token={ev['token']}")) as mic:
                await mic.wait("ready")
                await mic.ws.send(bytes(4096))
                assert "language" in (await mic.wait("error", timeout=5))["error"]
        run(go())

    def test_not_configured(self, server, monkeypatch):
        monkeypatch.setenv("GNANI_API_KEY", "")
        ev = httpx.post(server + "/api/events", json={}).json()
        async def go():
            async with Socket(ws(server, f"/ws/events/{ev['code']}/audio?token={ev['token']}")) as mic:
                assert "not set up" in (await mic.wait("error"))["error"]
        run(go())
