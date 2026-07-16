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

## 2026-07-13 — Phase 1 phantom-edge bug FIXED (fleet-status catch)

Fleet status found the Phase-1 runner had emitted ~46k phantom entries (51/cycle). Root cause:
on short-dated intraday KXBTCD contracts the driftless digital saturates (sigma*sqrt(T)->0 ⇒
p_fair clamps to ~0/1), and the strategy "picked up pennies" buying the near-certain side at
$0.99 for the maker rebate where model and market AGREE (both ~1%) — not edge, a clamp artifact.

Fixed (3 gates, all fail-closed):
- `strategy/signal.py`: probability-space edge PER SIDE from the price we'd pay (YES buy → market
  P(YES)≈yes_bid; NO buy → ≈1-no_bid); require |p_fair - market| >= 0.05. Never depends on yes_mid
  (deep-OTM books lack a yes_ask, which let the first fix leak 7/cycle).
- `strategy/fair_value.py::is_saturated`: reject a clamped fair value (no real view).
- `strategy/runner.py`: MIN_TTE_DAYS=0.5 — skip near-expiry step-function regime.
Verified live: 51 → 7 (intermediate) → **0 entries/cycle** (52 rejects). Purged all phantom
entries from decisions.ndjson (46,100 + 14). 19 strategy tests green. Runner restarted clean.
The strategy now trades only a genuine >=5pt disagreement on a multi-day, non-saturated contract —
which may be rare (efficient market), itself the honest finding the KILL_N test will measure.

## 2026-07-15 — STALE alarm root-caused + fixed (phase0 capture daemon was unloaded)
Umbrella fleet-liveness flagged btc-bot STALE (state.json frozen since 2026-07-12 00:38, 3.7d).
Root cause: `com.btcbot.phase0_capture` was NOT loaded in launchd (missing from `launchctl list`)
— it is the only writer of data/state.json and data/captures.jsonl. The Phase-1 strategy loop
(PID 680) was healthy the whole time (cycling every 120s, phase1_positions.jsonl fresh same-day),
so no strategy data was lost; only the capture/snapshot stream stopped. Gap: ~3.7 days of captures
missing (Jul 12 00:38 → Jul 15 16:48). Fix: `launchctl bootstrap gui/501 launchd/com.btcbot.phase0_capture.plist`
— verified capture resumed (spot_ok=True, 20 markets, state.json rewritten). All three btcbot
jobs now loaded. Open question: what unloaded it on Jul 12 (likely reboot/login race or manual
bootout); if it recurs, add KeepAlive audit or a self-heal to fleet_liveness.

## 2026-07-16 — Phase-1 kill-window scoreboard (Grok; handoff from Claude)

Built the join the kill test was missing. No strategy changes, no LLM, no live path.

**Code**
- `measurement/settlement.py` — `phase=` param + `realized_pnl_side` (YES/NO, reuses fee_for_role).
- `measurement/phase1_score.py` — post-fix cutoff (2026-07-13), kill verdict, TTE buckets, MD formatter.
- `deploy/run_phase1_settlements.py` — joins `phase1_positions.jsonl` → Kalshi `market.result` →
  `data/phase1_settlements.jsonl` (maker, keyed by decision_id).
- `deploy/phase1_scoreboard.py` → `PHASE1_SCOREBOARD.md`.
- `tests/test_phase1_scoreboard.py` — fee-honest loss, FLOOR vs edge-candidate, pre-fix exclusion.
- Suite: **34** unit tests green (`-m "not integration"`).

**Real run (2026-07-16 ~20:15Z)**
- Open considered: 6,230 post-fix entries.
- Newly settled: **2,425** (Jul 14–15 markets resolved). Still pending: **3,805** (mostly Jul 16).
- Mean net EV/contract: **−0.115060**. Win%: **0.91%** (22/2425). Total net: **−$279.02**.
- Verdict: **FLOOR (mean ≤ 0)** (N ≫ KILL_N=150).
- TTE: all 2,425 in 0.5–1d bucket — claimed min-TTE gate looks respected.
- Penny read: **42.9%** of settled entries had entry_price ≤ $0.05; median entry $0.08.
  Residual "pick up pennies on the cheap side of a large disagreement," not rare multi-day edges.
- Unique tickers among settled: **33** only — cycle re-entry inflates N. Even first-per-ticker
  mean net still negative (~−$0.048/contract).

**Not done (out of scope):** loop gate, anchor B, live, de-dupe runner. Re-run settle+scoreboard
after Jul-16 markets resolve before treating the floor as the final window close if you want the
open 3,805 included — direction is already unambiguous on the settled set.


## 2026-07-16 — VERDICT: Anchor A FLOORED; Anchor B pre-registered
Grok built the Phase-1 kill-window scoreboard (join entries→settlements, fee-honest, `PHASE1_SCOREBOARD.md`). Result: N=2,425 settled, mean net_ev_oos=−$0.115/contract, win 0.91%, total −$279 → FLOOR by the pre-registered rule (KILL_N=150 settlements, ≤0). Claude independently re-derived + caveat: the 2,425 are only 33 unique markets re-logged ~73× (a real re-entry bug); on independent N=33 mean=−$0.048 (95% CI crosses zero). Floor is unambiguous by direction on every cut (43% ≤5¢ penny-entries; Phase-0 book baseline −$0.007) → owner ACCEPTED the floor. Verdict stamped in `EFFICACY_TEST_BTC_2026-07-11.md` §6. btc-bot NOT buried — advances to Anchor B (options-implied/IBIT), pre-registered in `EFFICACY_TEST_BTC_B_2026-07-16.md` (KILL_N now counts INDEPENDENT markets + requires t≥2). Prerequisite before B's window: fix the re-logging bug (`GROK_HANDOFF_PHASE1_DEDUP.md`). No live, no LLM.
