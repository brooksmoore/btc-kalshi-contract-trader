#!/usr/bin/env bash
# Poll for resolved markets every 5 minutes; write settlements.jsonl
set -euo pipefail
BOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${BOT}:/Users/brooksmoore/Desktop/umbrella"
export KALSHI_ENV=prod
PY="${PHASE0_PYTHON:-/Users/brooksmoore/Desktop/umbrella/.venv/bin/python}"
cd "$BOT"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting phase0 settle daemon" >> /tmp/btc_phase0_settle.log
while true; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) settle poll" >> /tmp/btc_phase0_settle.log
  "$PY" deploy/run_phase0_settlements.py >> /tmp/btc_phase0_settle.log 2>&1 || true
  # progress line for easy tail
  CAP=$(wc -l < data/captures.jsonl 2>/dev/null | tr -d ' ' || echo 0)
  SET=$(wc -l < data/settlements.jsonl 2>/dev/null | tr -d ' ' || echo 0)
  DEC=$(wc -l < data/decisions.ndjson 2>/dev/null | tr -d ' ' || echo 0)
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) progress captures=$CAP settlements=$SET decisions=$DEC" >> /tmp/btc_phase0_settle.log
  sleep 300
done
