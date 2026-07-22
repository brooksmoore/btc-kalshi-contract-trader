# btc-bot — STATUS

> Standardized header. Keep these fields at the very top, always current.

- **One-liner:** Kalshi short-horizon BTC event-contract experiment — paper measurement first.
- **Stage:** **Phase 1.5 fill-honest RUNNING** (primary for any future live talk). Intent scoreboard diagnostic. Anchor B OBSERVE-ONLY (window CLOSED).
- **Live gate:** OFF — `paper_trade=True`; never places orders. **Do not flip live** until fill-honest KILL_N met green.
- **Tests:** fill-honest **8/8** green + prior phase0/phase1 suite
- **Intelligence type:** Measurement only; no LLM in pricing path
- **Single most important next thing:** Daily fill-honest cook (primary). **15m S1 capturing** (zero rests); S2 locked until S1.5 + your yes.
- **Honest odds this makes money:** Still unproven on daily. 15m is binary CF-BRTI up — separate thesis; S2 not open.
- **Last updated:** 2026-07-22 — 15m S1 capture daemon deployed (Claude); capture-only, S2 still locked
- **Daemons:** `phase0_capture` ✅, `phase0_settle` ✅, `phase1_strategy` ✅ (PID active; cycles with **entries=0**), **`phase1_fill_score`** ✅ every 15m
- **Commands:**
  - **Primary (auto):** launchd `com.btcbot.phase1_fill_score` → settle + `PHASE1_FILL_SCOREBOARD.md`
  - Manual: `bash deploy/run_phase1_fill_scoreboard_job.sh`
  - Intent (diagnostic): `python deploy/run_phase1_settlements.py && python deploy/phase1_scoreboard.py`
  - Micro-live gate (NOT armed): `EFFICACY_TEST_BTC_MICRO_LIVE_2026-07-18.md`

---

## Phase 1.5 fill-honest (PRIMARY — go/no-go for micro-live)
| Item | Status |
|------|--------|
| Pre-reg | ✅ `EFFICACY_TEST_BTC_FILL_HONEST_2026-07-18.md` |
| Virtual orders | `phase1_virtual_orders.jsonl` — **62+** events; **~31 resting**, **9 filled**, **22 cancelled** (post-fix) |
| Fill rule | later `ask ≤ limit` (trade-through); no same-cycle free fill — **unchanged** |
| Scoreboard | `PHASE1_FILL_SCOREBOARD.md` (refreshed 2026-07-20 ~20:44Z) |
| Funnel | filled **9** / cancelled **22** / resting **31** → **fill rate ~29%** (was 4.5%) |
| N_filled (settled) | **0** (9 fills still `pending_result`) |
| Open gate | **fill-honest only** (intent diagnostic no longer blocks new rests) |
| Market fetch | paginated KXBTCD → **~210** open markets (was 50/page, starved multi-day) |
| Verdict | **INSUFFICIENT** (N_settled=0) — pipeline unstuck; watch toward KILL_N=100 |
| Auto score | ✅ `com.btcbot.phase1_fill_score` every **15 min** → `/tmp/btc_phase1_fill_score_launchd.log` |
| Live | **OFF** |

## Micro-live gate (pre-registered, NOT open)
| Item | Status |
|------|--------|
| Doc | `EFFICACY_TEST_BTC_MICRO_LIVE_2026-07-18.md` |
| Size / kill | 1 contract; max 3 open; −$15 hard stop; KILL_N=30 fills |
| Prerequisites | fill-honest CONTINUE + audit + Brooks same-session yes |
| Window | **CLOSED** — do not arm |

## Anchor B (pre-window)
| Item | Status |
|------|--------|
| Deribit → RN digital library | ✅ `measurement/anchor_b_pricing.py` |
| Unit tests | ✅ deep ITM/OTM/ATM, N(d2)≈BL, term interp, fail-closed |
| Observe harness | ✅ logs only; `mode=observe`, `phase=pre_window` |
| Counted decisions | ❌ none |
| Efficacy window | **CLOSED** |

## Phase 1 intent scoreboard (DIAGNOSTIC only) — refreshed 2026-07-18 ~20:02 local
| metric | independent | raw (diagnostic) |
|--------|------------:|-----------------:|
| N | **73** | 6230 |
| mean net | **+0.293677** | +0.082908 |
| t-stat | **+5.50** | — |
| win % | **50.7%** | 50.7% |
| total net | **+$21.44** | — |
| still open | 577 decision_ids (a few 429s left pending) | |
| verdict | **edge candidate (mean > 0, N&lt;150 keep going)** | PASS if scored raw (inflated) |

### By TTE (independent) — important
| bucket | N | mean net | win% |
|--------|--:|---------:|-----:|
| 0.5–1d | 34 | −0.034 | 11.8% |
| 1–3d | 39 | **+0.580** | 84.6% |

## 15m parallel lane (NOT daily)
| Item | Status |
|------|--------|
| Design | `DESIGN_15M.md` (updated for Claude fixes) |
| Pre-reg | `EFFICACY_TEST_BTC_15M_FILL_HONEST_2026-07-21.md` — **S2 CLOSED** |
| Stage | **S1 capture-only** (product + refs + books). Zero rests. |
| B1 shape | **binary_brti_up_vs_open** (CF BRTI 60s avg end ≥ open) — not brackets |
| B2 oracle | Kalshi `result` only for P&L |
| M1/M2/M3 | LATE_REF=10s; `m15_vol`; `m15_calibration` (needs N≥30) |
| Command | `python deploy/run_m15_capture.py --once` |
| Report | `M15_S1_PRODUCT_REPORT.md` |
| experiment_id | `btc-m15-fill-honest` |
| S2 | Locked until S1.5 + Brooks yes |
| Live | **OFF** |

## Recent movement
- 2026-07-22 (later): 🟢 **15m S1 capture daemon deployed (Claude, Brooks-authorized).** `com.btcbot.m15_capture` launchd (KeepAlive, own process, isolated from daily phase1) runs `deploy/run_m15_capture_daemon.sh` → `run_m15_capture.py --interval 5`. Persistent ~5.5s loop so a newly-opened 15m market is first-seen ≤10s → earns kill-eligible `ok` refs. Verified live: PID up, exit 0, `rests:0 orders:0`, shape `binary_brti_up_vs_open all_ok=true`. Current window joined mid-flight → `late` (expected); first `ok` refs accrue at the next :00/:15/:30/:45 boundary. Log `/tmp/btc_m15_capture_launchd.log`. **Still capture-only; S2 locked** (needs calib N≥30 + Brooks in-session yes). Live OFF.
- 2026-07-22: 🟢 **15m S1 + Claude fixes (Grok).** Capture-only runner live; product shape confirmed binary CF BRTI up; settlement oracle locked; LATE_REF 10s; short vol + calib gate modules; 15 tests. S2 still locked. Results → `umbrella/inbox/GROK_TO_CLAUDE_btc_15m_s1_FIXES_RESULTS.md`.
- 2026-07-21: 📋 **15m S0 scaffold (Grok).** Parallel KXBTC15M fill-honest design + pre-reg (CLOSED) + pure open-ref/fair-value modules + tests. No runner, no launchd, daily Phase 1.5 untouched. Claude eval handoff: `umbrella/inbox/GROK_TO_CLAUDE_btc_15m_scaffold_EVAL.md`.
- 2026-07-20 (evening): 🟢 **Fill-starvation fix (Grok).** Root causes: (1) intent open set (100+ tickers) blocked new rests even after fill-honest cancel; (2) market fetch limit 50 / no cursor → multi-day KXBTCD missing. Fixes: `open_tickers_phase15` (fill-honest-only gate), paginated `fetch_btc_markets` (210 KXBTCD), light 429 retry. One cycle after fix: **entries=21**, then **9 filled / 31 resting / fill rate 29%**. Live OFF. 59 core tests green. Kill rules unchanged.
- 2026-07-20: 🔍 **Health check (Grok).** Fill-honest scoreboard re-run: funnel 1 fill / 21 cancel / fill rate 4.5%; N_settled still 0 (1 open fill pending market result). phase1 strategy alive but **no new rests** since 07-19 (entries=0, skips~101). Live still OFF. STATUS + LEDGER updated. No code change this pass.
- 2026-07-18 (evening): 🟢 **Auto fill-score job + micro-live pre-reg.** `com.btcbot.phase1_fill_score` installed (15m settle+scoreboard, paper-only; first run OK). Wrote `EFFICACY_TEST_BTC_MICRO_LIVE_2026-07-18.md` (1c, hard stops, twin sim) — **window not open**, no orders.
- 2026-07-18 (later): 🟢 **Phase 1.5 fill-honest paper deployed.** Virtual maker rests + trade-through fills + cancel-on-edge-gone; settle/scoreboard only on **filled** bets. Pre-reg efficacy locked. 8 unit tests green. `phase1_strategy` kickstarted (new PID). **Live still OFF.** Intent +$21 is diagnostic only.
- 2026-07-18: 🟢 **Scoreboard refresh.** Settled **+3,805** new rows (2425→6230 raw; independent **33→73**). Independent mean flipped **−4.8¢ → +29.4¢/bet** (t=5.50). Verdict: edge candidate only until N≥150. Still-pending ~577 (some Kalshi 429s mid-run). No strategy/live change.
- 2026-07-17: 🟢 **Umbrella emit un-broken (was silently failing).** btc runs under `umbrella/.venv`, whose editable umbrella_core `.pth` was being skipped (py3.12 finder issue) → `import umbrella_core` failed → phase0/phase1 snapshot+decision emit silently non-fatal for who-knows-how-long. Fixed: fresh non-editable `umbrella-core==0.1.1` into `umbrella/.venv` (verified `umbrella_core.decisions` importable from neutral cwd, 16 modules); kickstarted `com.btcbot.phase1_strategy` + `phase0_settle` to pick it up. ⚠️ `com.btcbot.phase0_capture` (the state.json writer, PID 38434) is running OLD code from a `.plist.disabled` file — left untouched (killing it risks stopping state.json with no auto-restart); needs a deliberate re-enable+restart. Part of a fleet-wide umbrella_core staleness sweep (multi/btc/hood were broken; pma ok).
- 2026-07-16 (later): **Legacy live channel quarantined.** `deploy/run_bot.py --env prod` without `--paper` hard-refuses (SystemExit 2; no `input()` confirm, no live Trader). `Trader(paper_trade=False)` requires env `BTC_LIVE_CONFIRM=ARM-REAL-MONEY`. Phase-1 paper path untouched. 5 new quarantine tests.
- 2026-07-16: Anchor B pricing engine + observe-only validation (window stays closed).
- 2026-07-16: Re-entry dedup; independent scoreboard primary.
- 2026-07-16: Scoreboard join; A interim reads.
- 2026-07-15: phase0_capture re-bootstrap after STALE.
- 2026-07-13: phantom-edge gates.
