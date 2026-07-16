# btc-bot — STATUS

> Standardized header. Keep these fields at the very top, always current.

- **One-liner:** Kalshi short-horizon BTC event-contract experiment — paper measurement first (Phase 0).
- **Stage:** **Phase 1 RUNNING + SCOREBOARD LIVE** — cost-honest baseline (anchor A: spot+RV), paper. Phase 0 complete. Kill-window interim read: **FLOOR direction** (see `PHASE1_SCOREBOARD.md`).
- **Live gate:** OFF — `paper_trade=True`; never places orders
- **Tests:** 34 unit tests green (`test_phase0_*` + `test_phase1_strategy` + `test_phase1_scoreboard`; integration spot deselected)
- **Intelligence type:** Measurement only (spot + book + fees); no strategy edge claims yet
- **Single most important next thing:** **Phase-1 scoreboard shipped 2026-07-16.** Settled **2,425** post-fix paper entries (maker fees); mean net **−$0.115/contract**, win% **0.91%**, total net **−$279**. Verdict line: **FLOOR (mean ≤ 0)** at N≫KILL_N=150. **3,805** Jul-16 entries still open (re-run `deploy/run_phase1_settlements.py` after those markets resolve). Penny signature real: **43%** of settled entries had entry ≤$0.05; only **33** unique tickers (cycle re-entry inflates N). Min-TTE≥0.5d respected on settled sample. **Do not invent edge** — pre-registered successor on final floor is anchor **B (options-implied / IBIT)**, not more tuning of A. Optional: de-dupe entries per ticker per day so N ≈ independent bets.
- **Honest odds this makes money:** Low on anchor A given this interim scoreboard. The realistic prior stands: Kalshi BTC digitals priced by counterparties who can also compute fair value. 97% backtest still **not** evidence.
- **Last updated:** 2026-07-16 (Phase-1 kill-window scoreboard + first real settle join)
- **Daemons (launchd, reboot-safe after login):**  
  - `com.btcbot.phase0_capture` — KeepAlive, every 120s, prod reads  
  - `com.btcbot.phase0_settle` — StartInterval 300s  
  - `com.btcbot.phase1_strategy` — Phase-1 paper loop  
  - Plists: `launchd/*.plist` + `~/Library/LaunchAgents/`  
  - Logs: `/tmp/btc_phase0_capture_launchd.log`, `/tmp/btc_phase0_settle_launchd.log`  
  - Scoreboard (manual): `python deploy/run_phase1_settlements.py` then `python deploy/phase1_scoreboard.py`

---

## Stage vocabulary
`idea → skeleton → core-done → runner-wiring → paper-validating → live-gated → live`

## Phase 0 checklist
| Item | Status |
|------|--------|
| 0.1 Independent BTC spot (Coinbase) | ✅ |
| 0.2 Kalshi bid/ask capture | ✅ |
| 0.3 Decision log | ✅ |
| 0.4 Settlement recorder | ✅ |
| 0.5 Fee model + unit tests | ✅ |
| 0.6 Anti self-score gate | ✅ |
| 0.7 Honest scoreboard / snapshot | ✅ |
| Exit: ≥50 settlements | ✅ (Phase 0 closed N=317; now 700+) |

## Phase 1 scoreboard (2026-07-16)
| Item | Value |
|------|------:|
| N settled (post 07-13) | 2425 |
| mean net EV/contract | −0.115060 |
| win % | 0.91% |
| verdict | **FLOOR (mean ≤ 0)** |
| still open | 3805 |
| full writeup | `PHASE1_SCOREBOARD.md` |

## How to run
```bash
cd ~/Desktop/btc-bot/Short-term\ Bitcoin\ Contract\ Trader\ Bot
export PYTHONPATH=".:$HOME/Desktop/umbrella"
# Phase 0 capture / settle
python deploy/run_phase0_capture.py --once
python deploy/run_phase0_settlements.py
# Phase 1 paper loop
python deploy/run_phase1.py --once
# Phase 1 kill-window
python deploy/run_phase1_settlements.py
python deploy/phase1_scoreboard.py
# tests
/usr/local/bin/python3.11 -m pytest tests/test_phase0_*.py tests/test_phase1_*.py -q -m "not integration"
```

## Recent movement
- 2026-07-16: **Anchor A FLOORED** (mean net −$0.115/contract, N=2,425 settled; −$0.048 on 33 independent markets, CI crosses zero) — owner accepted the floor. Advancing to **Anchor B** (options-implied/IBIT), pre-registered `EFFICACY_TEST_BTC_B_2026-07-16.md`. Prereq: fix re-logging (`GROK_HANDOFF_PHASE1_DEDUP.md`). Scoreboard: `PHASE1_SCOREBOARD.md`.
- 2026-07-16: **Phase-1 scoreboard** — join positions→settlements, kill verdict, TTE/penny notes. Handoff DONE.
- 2026-07-15: phase0_capture daemon re-bootstrapped after 3.7d STALE.
- 2026-07-13: phantom-edge bug fixed (prob edge + saturation + min TTE).
- 2026-07-12: Phase 1 built + deployed.
- 2026-07-11: Phase 0 closed; efficacy test pre-registered.
- 2026-07-10: Phase 0 implemented + roadmap.
