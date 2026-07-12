# LEDGER — btc-bot

Append-only.

## 2026-07-10 — Phase 0 measurement plane shipped (Grok)

Built `measurement/` package and capture runner. Live one-shot capture (prod API read, `paper_trade=True`):

- Independent spot: Coinbase BTC-USD **~$63,922**
- Kalshi markets: **15** open (15m + daily brackets)
- All 15 measurement_ok with real yes_bid/yes_ask
- **15** umbrella-valid `hold` decisions with `ref_price=yes_ask`, `entry_price_source=kalshi_yes_ask`, `benchmarks.BTC_USD`
- Settlements: **0** (need market resolution + poller runs)
- Unit tests: **11** passed (fees, self-score ban, hermetic spot)
- No orders placed

Anti-goals held: no strategy claims, no leverage, no self-score path.

## 2026-07-10 — Phase 0 daemons left running (prod reads)

- Capture: `run_phase0_capture.py --loops 2160 --interval 120 --max-markets 20` (KALSHI_ENV=prod, paper_trade=True)
- Settle: poll every 300s via `run_phase0_settle_daemon.sh`
- Logs: `/tmp/btc_phase0_capture.log`, `/tmp/btc_phase0_settle.log`
- ETA to N≈50 settlements: see status reply to Brooks (~0.5–2 days depending on 15m market rollover)

## 2026-07-10 — Phase 0 made reboot-safe (launchd)

Installed user LaunchAgents:
- `com.btcbot.phase0_capture` (KeepAlive + RunAtLoad, KALSHI_ENV=prod)
- `com.btcbot.phase0_settle` (StartInterval 300s + RunAtLoad)

Ad-hoc nohup processes stopped. Capture state=running; settle runs on interval (idle between polls). Settlements were already 20 at install time.

## 2026-07-11 — Phase 0 CLOSED (N=317); Phase 1 pre-registered

Verified the meter against the actual data (not the summary): `data/settlements.jsonl` = 317
settlements (317 unique tickers), mean net **−0.01267/contract**, sum **−$4.017**. Phase 0 exit
bar (≥50 settlements with real bid/ask + independent spot + fee fields) is met ~6x over. Result is
a fee/meter reality check ("blind buy-YES-touch-and-hold loses ~1.3¢/contract after fees"), NOT a
strategy verdict — self_score_guard kept it honest (no 97%-artifact).

Wrote `EFFICACY_TEST_BTC_2026-07-11.md` — the pre-registered Phase 1 kill test (metric = mean net
EV/contract OOS; maker-first; KILL_N=150 / min 100; FLOORED if net_ev_oos ≤ 0; strategy decisions
emitted as type:prob, kept separate from Phase-0 hypotheticals). Added a pre-committed successor:
if fair value A (spot+realized-vol) floors, the next premise is fair value B (options-implied/IBIT),
a structurally different input — so a floor advances the anchor rather than ending btc-bot or
silently re-testing A. This closes the known RV-vs-IV miscalibration risk (the kalshi-weather
failure mode) up front.

Phase 1 BUILD is gated on this pre-registration, so it can wait for Grok Build (returns 2026-07-15)
with zero critical-path cost. No code changed this session — Phase 0 closure + pre-registration only.

## 2026-07-12 — Phase 1 BUILT + DEPLOYED (anchor A: spot + realized vol)

Built the cost-honest baseline strategy per EFFICACY_TEST_BTC_2026-07-11.md. Scoped to KXBTCD
strike contracts (strike parsed from the `-T<price>` ticker suffix); KXBTC15M "up in 15 min?"
explicitly skipped (needs a window-open reference the capture data lacks).

- `strategy/fair_value.py` — driftless BS digital P(S_T≥K)=N(d2), realized_vol_annual, strike
  parse, tte. Pure/fail-closed.
- `strategy/signal.py` — maker-first, net-edge-gated entry reusing measurement.fees.net_ev_per_contract
  (no new fee math). Trade only if maker net EV > floor.
- `strategy/runner.py` — pure per-market price_and_signal_market + build_strategy_decision
  (emits type:prob, experiment_id=btc-phase1-strategy, kept separate from Phase-0 hypotheticals).
- `deploy/run_phase1.py` — paper loop (never places orders); accumulates its own evenly-spaced
  spot series for RV. Deployed via launchd `com.btcbot.phase1_strategy` (120s).
- 15 strategy unit tests (hand-computed digital, edge-gating, skip/entry paths, vol guard). Fee +
  self-score gates still green.

**Smoke test caught a real bug before it could pollute the test:** seeding RV from the captures
tail gave duplicate/clustered spots → vol=0.0346 (3.46%, ~16x too low) → overconfident digital →
**52 phantom entries, 0 rejects**. Fixed: (1) removed the seed — the runner accumulates its own
clean series; (2) added `vol_is_plausible` (10–300% annualized) + a ≥20-sample minimum, both
fail-closed (no trades on an untrustworthy vol); (3) purged the 52 phantom entries from
decisions.ndjson so the window isn't contaminated. Verified clean-start now fail-closes
("accumulating spot history (n/20)").

Also stopped + disabled the Phase-0 capture daemon (19,835 captures / 317 settlements — enough);
kept the settle poller for resolving strategy trades. Phase 1 runner live 2026-07-12; window opens
at first counted trade once vol is stable. No live gate, no leverage, no LLM in the pricing path.
