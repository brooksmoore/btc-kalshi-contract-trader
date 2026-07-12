# btc-bot — STATUS

> Standardized header. Keep these fields at the very top, always current.

- **One-liner:** Kalshi short-horizon BTC event-contract experiment — paper measurement first (Phase 0).
- **Stage:** **Phase 1 RUNNING** (built + deployed 2026-07-12) — cost-honest baseline strategy, paper. Phase 0 complete (N=317).
- **Live gate:** OFF — `paper_trade=True`; never places orders
- **Tests:** 11 Phase-0 unit tests green (fees, self-score guard, hermetic spot)
- **Intelligence type:** Measurement only (spot + book + fees); no strategy edge claims yet
- **Single most important next thing:** Phase 1 is BUILT + RUNNING (`deploy/run_phase1.py` via launchd `com.btcbot.phase1_strategy`, 120s paper loop). It fail-closes (no trades) until ≥20 evenly-spaced spot samples yield a plausible realized vol (10–300% annualized) — guards added after a smoke test caught a degenerate seed making 52 phantom entries (purged). **Watch:** once vol stabilizes, confirm it emits sane `type:prob` strategy entries (KXBTCD only; strike from ticker) and that they resolve via the settle poller, kept separate from Phase-0. Score grey-until-KILL_N=150, FLOORED if net_ev_oos ≤ 0; on floor, successor anchor = options-implied (B). **⚠️ Not version-controlled** — this repo has no git; Phase 1 work is local-only (see report).
- **Honest odds this makes money:** Low-to-moderate, unproven. The realistic prior: Kalshi BTC digitals priced by counterparties who can also compute fair value; edge requires a genuine wedge (prediction-market vs options) or Kalshi being slower. 97% backtest still **not** evidence.
- **Last updated:** 2026-07-11 (Phase 0 closed at N=317; Phase 1 pre-registration written)
- **Daemons (launchd, reboot-safe after login):**  
  - `com.btcbot.phase0_capture` — KeepAlive, every 120s, prod reads  
  - `com.btcbot.phase0_settle` — StartInterval 300s  
  - Plists: `launchd/*.plist` + `~/Library/LaunchAgents/`  
  - Logs: `/tmp/btc_phase0_capture_launchd.log`, `/tmp/btc_phase0_settle_launchd.log`  
  - Stop: `launchctl bootout gui/$(id -u)/com.btcbot.phase0_capture` (same for settle)

---

## Stage vocabulary
`idea → skeleton → core-done → runner-wiring → paper-validating → live-gated → live`

## Phase 0 checklist
| Item | Status |
|------|--------|
| 0.1 Independent BTC spot (Coinbase) | ✅ |
| 0.2 Kalshi bid/ask capture | ✅ first cycle: 15 markets |
| 0.3 Decisions with real `ref_price` (yes_ask) | ✅ 15 holds schema-valid |
| 0.4 Settlement recorder | ✅ module + poller script |
| 0.5 Fee model + unit tests | ✅ taker@50¢ = 1.75¢ |
| 0.6 Anti self-score gate | ✅ forbids model_own_price path |
| 0.7 Honest scoreboard / snapshot | ✅ phase0 warnings; no 97% claim as evidence |
| Exit: ≥50 settlements | ⏳ settlements_n=0 (need resolved markets + poller) |

## How to run
```bash
cd ~/Desktop/btc-bot/Short-term\ Bitcoin\ Contract\ Trader\ Bot
export PYTHONPATH=".:$HOME/Desktop/umbrella"
# one capture (no orders)
python deploy/run_phase0_capture.py --once
# spot only
python deploy/run_phase0_capture.py --spot-only
# after markets resolve
python deploy/run_phase0_settlements.py
# tests
python -m pytest tests/test_phase0_*.py -q -m "not integration"
```

## Recent movement
- 2026-07-10: **Phase 0 implemented** — `measurement/` (fees, spot, book, capture, settlement, self_score_guard); `deploy/run_phase0_capture.py` + settlements poller; live cycle wrote 15 captures @ spot ~$63,922, 15 umbrella decisions with `kalshi_yes_ask` ref_price. 11 unit tests green.
- 2026-07-10: Roadmap written (`BTC_ROADMAP.md`); Claude+Grok alignment on bounded paper experiment.
- 2026-07-07: Snapshot/decision path wiring to umbrella; artifact warnings.
