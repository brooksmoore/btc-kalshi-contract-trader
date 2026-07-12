#!/usr/bin/env bash
# Phase 0 capture + settlement daemon (prod reads, never places orders).
# Logs: /tmp/btc_phase0_capture.log  /tmp/btc_phase0_settle.log
set -euo pipefail
BOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${BOT}:/Users/brooksmoore/Desktop/umbrella"
export KALSHI_ENV=prod
PY="${PHASE0_PYTHON:-/Users/brooksmoore/Desktop/umbrella/.venv/bin/python}"
cd "$BOT"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting phase0 capture daemon" >> /tmp/btc_phase0_capture.log
# ~3 days at 2 min interval: 3*24*30 = 2160 cycles
exec "$PY" deploy/run_phase0_capture.py --loops 2160 --interval 120 --max-markets 20 \
  >> /tmp/btc_phase0_capture.log 2>&1
