#!/usr/bin/env bash
# S1 KXBTC15M capture-only daemon (refs + books + product shape).
# PAPER ONLY — zero rests, zero orders, live OFF. Own process (isolated from daily phase1).
#
# Persistent loop at --interval 5s so a newly-opened 15m market is first observed
# within ~7-8s of open → earns a kill-eligible `ok` window ref (LATE_REF_SECONDS=10).
# launchd KeepAlive restarts it if it dies.
set -euo pipefail

ROOT="/Users/brooksmoore/Desktop/btc-bot/Short-term Bitcoin Contract Trader Bot"
PY="/Users/brooksmoore/Desktop/umbrella/.venv/bin/python"
export PYTHONPATH="${ROOT}:/Users/brooksmoore/Desktop/umbrella${PYTHONPATH:+:$PYTHONPATH}"
export KALSHI_ENV="${KALSHI_ENV:-prod}"
cd "$ROOT"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] m15_capture daemon start (--interval 5, capture-only)"
exec "$PY" deploy/run_m15_capture.py --interval 5
