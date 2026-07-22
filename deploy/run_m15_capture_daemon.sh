#!/usr/bin/env bash
# S1 KXBTC15M capture-only daemon (refs + books + product shape).
# PAPER ONLY — zero rests, zero orders, live OFF. Own process (isolated from daily phase1).
#
# Persistent loop at --interval 2s to minimize poll granularity. NOTE (2026-07-22, S1 finding):
# Kalshi surfaces a new 15m market ~5-10s AFTER its nominal open_time, so even instant polling
# leaves first_seen near the 10s `ok` bar. Tight polling shaves our own granularity but does not
# remove Kalshi's surfacing lag — the robust fix (use market floor_strike as the official S_open,
# making the Coinbase-timing gate diagnostic-only) is flagged to Grok. launchd KeepAlive restarts.
set -euo pipefail

ROOT="/Users/brooksmoore/Desktop/btc-bot/Short-term Bitcoin Contract Trader Bot"
PY="/Users/brooksmoore/Desktop/umbrella/.venv/bin/python"
export PYTHONPATH="${ROOT}:/Users/brooksmoore/Desktop/umbrella${PYTHONPATH:+:$PYTHONPATH}"
export KALSHI_ENV="${KALSHI_ENV:-prod}"
cd "$ROOT"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] m15_capture daemon start (--interval 2, capture-only)"
exec "$PY" deploy/run_m15_capture.py --interval 2
