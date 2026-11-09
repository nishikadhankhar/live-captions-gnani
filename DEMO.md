# Live demo playbook

Goal: in front of the mentors, you speak, and what you say appears live on their phones.
They can also send you a question.

## Start it

```bash
cd live-room
./demo.sh
```

It starts everything, prints a **phone link** (`https://….trycloudflare.com`) and opens Chrome.
The phone link works on any network, including mobile data, with no certificate warning.
It stops working when you press Ctrl+C.

1. In Chrome: type the talk name → **Start captioning**. Put this window on the projector
   (full screen: ⌃⌘F).
2. The mentors scan the QR code. A captions page opens on their phone.
3. Tap **Start captioning** on the laptop → **Allow** the microphone → speak.

**Test the phone link on your own phone first.** If it says "site can't be reached", wait
10 seconds and try again (a brand-new link takes a moment to start working).

| Command | When |
|---|---|
| `./demo.sh` | Default: laptop + public phone link (needs internet) |
| `./demo.sh wifi` | Phones on the **same Wi-Fi** open `https://<laptop-ip>:5174` (certificate warning once). College Wi-Fi often blocks this. |
| `./demo.sh laptop` | No phone link |

## Rehearse once (5 minutes)

- [ ] Use **Google Chrome** on the laptop (captions use Chrome's speech recognition).
- [ ] Mic allowed (Chrome asks the first time, then remembers).
- [ ] Say a sentence: on your phone, words appear as you speak, then the finished line.
- [ ] Send a question from your phone → it appears under **Questions** on the laptop.
- [ ] Laptop: notifications off (Focus mode), charger in, internet working.

## 2-minute script

| You do | They see |
|---|---|
| "Captions at events usually mean a person typing, or nothing at all. Scan this." | QR code on the projector |
| Mentors scan. "No app, no sign-up." | Captions page on their phone; the laptop shows how many people are reading |
| Tap **Start captioning**, talk normally: "Hello, my name is …" | Their phones show your words as you say them |
| "If you have a question, tap Ask a question." | Their question appears on your screen |
| Tap **🎙 Answer**, say your answer, tap **✓ Done** | On their phones: the question as a card, your spoken answer under it |
| Tap **End event** | Captions end on every phone; everything is deleted |

Speak clearly at a normal pace and pause between sentences: each pause finishes a line.

## If something breaks

| Problem | Fix |
|---|---|
| Phone: "site can't be reached" | Wait 10 s and retry. Check demo.sh printed a `trycloudflare.com` link; "Tunnel failed" means the laptop has no internet. |
| QR area says phones can't open "localhost" | demo.sh isn't running or the tunnel failed. Restart `./demo.sh`. |
| Mic won't start / "permission denied" | Chrome address bar → 🔒 → Microphone → Allow, then reload |
| "Speech recognition: network" | No internet. Switch to a phone hotspot. |
| Captions stop | They restart by themselves; if not, tap Stop then Start captioning |
| Phone shows "Waiting for the speaker" | The laptop isn't captioning: tap Start captioning |
