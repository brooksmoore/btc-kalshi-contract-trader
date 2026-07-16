# btc-bot — STATUS

> Standardized header. Keep these fields at the very top, always current.

- **One-liner:** Kalshi short-horizon BTC event-contract experiment — paper measurement first (Phase 0).
- **Stage:** **Phase 1 RUNNING + SCOREBOARD (independent N)** — anchor A paper. Re-entry bug **fixed 2026-07-16**. Anchor B window still closed (needs Brooks sign-off + options data path).
- **Live gate:** OFF — `paper_trade=True`; never places orders
- **Tests:** 38 unit tests green (`phase0` + `phase1_strategy` + `phase1_scoreboard` + `phase1_dedup`; integration spot deselected)
- **Intelligence type:** Measurement only (spot + book + fees); no strategy edge claims yet
- **Single most important next thing:** **Dedup shipped.** Runner now logs **≤1 open position per ticker** until settle. Scoreboard primary unit = **independent** bets. Independent read: **N=33**, mean net **−$0.048/bet**, win **9.09%**, **t=−0.90** → INSUFFICIENT under KILL_N (honest); raw inflated N=2425 was diagnostic only. Next: (1) re-run settle as Jul-16 markets resolve to grow independent N; (2) Brooks sign-off to open Anchor B after options path is wired — §0 prerequisite is **fixed & verified**.
- **Honest odds this makes money:** Low on anchor A (independent mean &lt; 0, t not significant). 97% backtest still **not** evidence.
- **Last updated:** 2026-07-16 (Phase-1 re-entry dedup + independent scoreboard primary)
- **Daemons (launchd):** `com.btcbot.phase0_capture`, `phase0_settle`, `phase1_strategy`
- **Scoreboard:** `python deploy/run_phase1_settlements.py` then `python deploy/phase1_scoreboard.py` (independent default)

---

## Stage vocabulary
`idea → skeleton → core-done → runner-wiring → paper-validating → live-gated → live`

## Phase 1 scoreboard (independent primary, 2026-07-16)

| metric | independent | raw (diagnostic) |
|--------|------------:|-----------------:|
| N | **33** | 2425 |
| mean net / unit | **−0.048185** | −0.115060 |
| win % | **9.09%** | 0.91% |
| t-stat | **−0.90** | — |
| verdict | **INSUFFICIENT (N&lt;100)** | FLOOR (inflated) |

Full table: `PHASE1_SCOREBOARD.md`

## How to run
```bash
cd ~/Desktop/btc-bot/Short-term\ Bitcoin\ Contract\ Trader\ Bot
export PYTHONPATH=".:$HOME/Desktop/umbrella"
python deploy/run_phase1.py --once
python deploy/run_phase1_settlements.py
python deploy/phase1_scoreboard.py
/usr/local/bin/python3.11 -m pytest tests/test_phase0_*.py tests/test_phase1_*.py -q -m "not integration"
```

## Recent movement
- 2026-07-16: **Re-entry dedup** — one open bet per ticker; independent scoreboard primary; Anchor B §0 verified.
- 2026-07-16: Phase-1 scoreboard join + first settle (raw FLOOR on inflated N).
- 2026-07-15: phase0_capture re-bootstrapped after 3.7d STALE.
- 2026-07-13: phantom-edge gates.
- 2026-07-12: Phase 1 deployed.
- 2026-07-11: Phase 0 closed; efficacy A pre-registered.
