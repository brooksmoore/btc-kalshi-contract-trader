# btc-bot — STATUS

> Standardized header. Keep these fields at the very top, always current.

- **One-liner:** Kalshi short-horizon BTC event-contract experiment — paper measurement first (Phase 0).
- **Stage:** **Phase 1 RUNNING** (built + deployed 2026-07-12) — cost-honest baseline strategy, paper. Phase 0 complete (N=317).
- **Live gate:** OFF — `paper_trade=True`; never places orders
- **Tests:** 11 Phase-0 unit tests green (fees, self-score guard, hermetic spot)
- **Intelligence type:** Measurement only (spot + book + fees); no strategy edge claims yet
- **Single most important next thing:** Phase 1 RUNNING clean (`deploy/run_phase1.py` via launchd `com.btcbot.phase1_strategy`, 120s paper loop). **2026-07-13: found + fixed a phantom-edge bug** — on short-dated contracts the digital saturated (p_fair→~0/1) and the strategy "picked up pennies" buying near-certain sides at $0.99 where model≈market (46k phantom entries, purged). Fixed with a per-side probability-edge gate (|p_fair − price| ≥ 0.05), a saturated-fair-value reject, and a 0.5-day min-TTE skip; verified **51 → 0 entries/cycle**. It now trades ONLY a genuine ≥5-point disagreement on a multi-day, non-saturated KXBTCD contract — which may be rare (efficient market), itself the honest finding. **Watch:** whether any real entry ever appears; score grey-until-KILL_N=150, FLOORED if net_ev_oos ≤ 0; on floor, successor anchor = options-implied (B). Now version-controlled: public repo `brooksmoore/btc-kalshi-contract-trader` (no secrets).
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
