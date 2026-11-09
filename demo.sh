#!/usr/bin/env bash
# One command for the live demo.
#
#   ./demo.sh          laptop at http://localhost:5173  +  a public https link for phones
#                      (Cloudflare quick tunnel: works on any Wi-Fi or mobile data)
#   ./demo.sh wifi     phones on the SAME Wi-Fi only (https on the laptop's Wi-Fi address)
#   ./demo.sh laptop   this laptop only (no phone link)
#
# Stop everything with Ctrl+C.
set -uo pipefail
cd "$(dirname "$0")"
MODE="${1:-tunnel}"
LOG="$(mktemp -d)"
rm -f .public_url

cleanup() { rm -f .public_url; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Free the ports if an old run is still around.
for port in 8000 5173 5174; do
  pids=$(lsof -ti tcp:$port 2>/dev/null || true)
  [ -n "$pids" ] && kill $pids 2>/dev/null || true
done
sleep 0.3

[ -f backend/.env ] || echo "⚠️  backend/.env has no GEMINI_API_KEY: captions still work, AI tone/catch-up fall back."
[ -d frontend/node_modules ] || (cd frontend && npm install --no-audit --no-fund)

echo "▶ backend   http://localhost:8000"
(cd backend && python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning) &

echo "▶ laptop    http://localhost:5173"
(cd frontend && npx vite --port 5173 --strictPort > "$LOG/vite.log" 2>&1) &

wait_for() {  # url, seconds
  for _ in $(seq 1 $(( $2 * 2 ))); do curl -sk -o /dev/null --max-time 2 "$1" && return 0; sleep 0.5; done
  return 1
}
wait_for http://127.0.0.1:8000/api/health 20 || { echo "❌ backend did not start"; exit 1; }
wait_for http://localhost:5173 30 || { echo "❌ frontend did not start (see $LOG/vite.log)"; exit 1; }

PHONE=""
if [ "$MODE" = "tunnel" ]; then
  if command -v cloudflared >/dev/null; then
    echo "▶ phones    creating a public link (takes ~5 s)…"
    cloudflared tunnel --no-autoupdate --url http://localhost:5173 > "$LOG/tunnel.log" 2>&1 &
    for _ in $(seq 1 60); do
      PHONE=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG/tunnel.log" | head -1)
      [ -n "$PHONE" ] && grep -q "Registered tunnel connection" "$LOG/tunnel.log" && break
      sleep 0.5
    done
    # A brand-new link takes a few seconds to exist. Asking too early makes the Mac
    # remember "no such address" for a while, so wait before the first check.
    [ -n "$PHONE" ] && sleep 6
    if [ -n "$PHONE" ] && wait_for "$PHONE/api/config" 45; then
      echo "▶ phones    $PHONE"
    else
      echo "⚠️  Tunnel failed (no internet?). Falling back to same-Wi-Fi mode."
      PHONE=""
      MODE="wifi"
    fi
  else
    echo "⚠️  cloudflared not installed (brew install cloudflared). Using same-Wi-Fi mode."
    MODE="wifi"
  fi
fi

if [ "$MODE" = "wifi" ]; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
  if [ -n "$IP" ]; then
    (cd frontend && HTTPS=1 npx vite --host 0.0.0.0 --port 5174 --strictPort > "$LOG/vite-https.log" 2>&1) &
    wait_for "https://localhost:5174" 30 && PHONE="https://$IP:5174"
    echo "▶ phones    $PHONE   (same Wi-Fi only; accept the certificate warning once)"
  else
    echo "⚠️  No Wi-Fi address found: phones can't open the captions. Connect to Wi-Fi or a hotspot."
  fi
fi

[ -n "$PHONE" ] && echo "$PHONE" > .public_url

[ -n "${NO_OPEN:-}" ] || open -a "Google Chrome" "http://localhost:5173" 2>/dev/null || open "http://localhost:5173"

cat <<EOF

Ready. In Chrome (this laptop):
  1. Type the talk name → Start captioning     (put this window on the projector)
  2. The audience scans the QR code${PHONE:+  (it points to $PHONE)}
  3. Tap "Start captioning" → allow the microphone → speak
     Captions appear live on every phone. Questions show up on the right.

Test the phone link first: open ${PHONE:-"(no phone link)"} on your phone.
Ctrl+C to stop.
EOF
wait
