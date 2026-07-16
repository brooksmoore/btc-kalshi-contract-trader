# Efficacy Test — btc-bot Phase 1, Anchor B (options-implied / IBIT digital fair value)

*Pre-registered 2026-07-16, BEFORE the Anchor-B build and BEFORE any counted Anchor-B trade. The
pre-committed successor to Anchor A, which FLOORED 2026-07-16 (`EFFICACY_TEST_BTC_2026-07-11.md` §6).
Same discipline that FLOORED kalshi_bot_2.0 and Anchor A: net-of-cost, maker-first, pre-committed
kill, no "it works" before KILL_N. This document is not edited once the window opens except to
append the verdict. Draft numbers below are for Brooks's sign-off; the window does not open until he
confirms them AND the re-logging fix is verified (§0).*

## 0. Hard prerequisite before the window opens (learned from Anchor A)

Anchor A's N was inflated ~73× because the Phase-1 loop re-logged the SAME contract every ~120s
(2,425 "settlements" = 33 real markets). **Anchor B's window MUST NOT open until the re-entry/
re-logging bug is fixed and verified** — one counted bet per genuine new market/signal, no
re-logging an open position. Otherwise KILL_N is meaningless. (Handoff: `GROK_HANDOFF_PHASE1_DEDUP.md`.)

**Status 2026-07-16: fixed & verified.**
- Runner: `deploy/run_phase1.py` skips entry when ticker already has an unsettled counted position
  (`measurement/phase1_dedup.py` + `should_count_new_entry`).
- Scoreboard primary unit: independent (one per ticker); raw cycle N is diagnostic only.
- Proof: `tests/test_phase1_dedup.py` (5 cycles → 1 entry; different strike still logs;
  independent N = unique tickers). Real scoreboard: raw N=2425 → independent N=33.
- Details: `umbrella/inbox/GROK_TO_CLAUDE_phase1_dedup_RESULTS.md`.

## 1. The strategy under test (ONE structurally-different anchor)

- **Primary fair value (B):** **options-implied / IBIT risk-neutral digital probability** for the
  contract's strike/expiry — a *forward-looking* input, structurally different from A's backward-
  looking realized vol. Source path (Deribit BTC options implied vol → risk-neutral digital, or
  IBIT-implied) stamped here when the data path is wired.
- **Signal:** trade a contract ONLY when Kalshi's price diverges from the options-implied fair value
  by MORE than round-trip cost (fee + spread). No wedge over cost → no trade (reject).
- **Execution:** **maker-first** (resting limit); NO taker-at-mid default. Paper only, no leverage,
  no LLM in the pricing path, no live gate.
- **One bet per market:** at most one counted entry per (ticker) per genuine signal — enforced by
  the §0 fix. Independent bets are the unit of N.

## 2. Metric & window

- **Metric:** mean net-of-cost EV per bet on OUT-OF-SAMPLE **independent** settlements (fee +
  pessimistic maker fill modeled; gross-only gates forbidden). Plus the effect-size bar below.
- **Effect-size bar (from Brooks's `the_record` harness):** report a **t-statistic** on mean net EV;
  a positive verdict requires **t ≥ 2** (mean > 0 by ≥2 standard errors), not just mean > 0. This is
  the guard Anchor A's deduped CI (which crossed zero) would have failed.
- **Emit:** each entry/reject is an umbrella decision `prediction.type="prob"`, tagged **anchor_b**,
  kept SEPARATE from Phase-0 and Anchor-A rows (no cross-contamination).
- **Window:** opens at the first counted Anchor-B trade AFTER §0 is verified (stamp date here).
  Runs unattended until **KILL_N independent settlements** or **≥14 days**, whichever serves the
  window. (14d, not 7d — independent N accrues ~1/70th as fast as A's inflated count; ~16 unique
  markets/day observed, so ~150 independent needs ~9–14 days.)

## 3. Pre-committed kill / verdict

- **KILL_N = 150 INDEPENDENT settlements** (hard minimum 100). Note the change from A: **independent
  markets, not raw settlements** — this is the fix for A's inflation. No verdict before N ≥ 100.
- **FLOORED** if `net_ev_oos ≤ 0` OR `t < 2` at N ≥ KILL_N. A floor is an honest process win.
- **CONTINUE** (to Phase 2 loop gate) only if `net_ev_oos > 0` AND `t ≥ 2` at N ≥ KILL_N.
- **INSUFFICIENT** (N < 100 at window end): extend the SAME window once (max +14d), or stop and
  record "not enough independent settlements." Never "it's working."

## 4. On FLOORED — the terminal read (both anchors dead)

If Anchor B also floors, then a *backward-looking* (A) AND a *forward-looking* (B) anchor both failed
to beat the Kalshi BTC digital book after fees. That is a strong, honest conclusion: **the book is
efficient to a retail maker** — the same lesson as kalshi_bot_2.0 weather. On a B-floor, the
pre-committed next step is **NOT** anchor C; it is **burial of the Kalshi-BTC-digital premise**
(`/postmortem` Mode 1), freeing the compute. No third anchor without a genuinely new edge source
(e.g. a latency/speed wedge, not another fair-value model), pre-registered separately.

## 5. On CONTINUE — the next gate (stated now so it isn't moved later)

Advance to the Phase-2 loop gate per `BTC_ROADMAP.md`. That gate needs its OWN pre-registered test
(mechanical-leak self-improvement, ≤$5/mo LLM cap) — not covered here. No live money at any point
without Brooks's in-session confirmation + a separate live gate test.

## 6. Explicitly NOT in Anchor B

Leverage · LLM in the pricing path · treating Phase-0 or Anchor-A rows as N · live gate · gross-only
scoring · any "edge" claim before KILL_N · re-logging the same market (the §0 bug).

## 7. Result (appended at window end — do not edit above)

- **Prerequisite (§0) fixed & verified:** **YES — 2026-07-16** (dedup runner + independent scoreboard;
  tests green; independent N tracks unique markets). Window still closed until Brooks sign-off + B data path.
- **Data path (B) wired:** _(pending)_
- **Window opened:** _(pending Brooks sign-off + §0 done)_
- **Verdict:** _(pending)_
