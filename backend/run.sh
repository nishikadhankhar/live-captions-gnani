#!/usr/bin/env bash
# Start the Live Captions API on http://localhost:8000 (docs at /docs)
cd "$(dirname "$0")"
exec python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT:-8000}"
