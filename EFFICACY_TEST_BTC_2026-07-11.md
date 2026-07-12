# Efficacy Test — btc-bot Phase 1 (cost-honest baseline strategy)

*Pre-registered 2026-07-11, BEFORE the Phase 1 build and BEFORE any counted trade. Numbers locked
per `BTC_ROADMAP.md` §4 + Phase 1 (1.5). Same discipline that FLOORED kalshi_bot_2.0: net-of-cost
scoring, maker-first, pre-committed kill, no "it works" before KILL_N. This document is not edited
once the window opens except to append the verdict.*

## 0. What Phase 0 established (and did not)

317 paper settlements, each a HYPOTHETICAL "buy YES at the ask and hold to resolve" with real
entry bid/ask + independent spot stamp + fee fields (self-score-guarded against the 97%-backtest
artifact). Result: mean net **−1.27¢/contract**, sum **−$4.02**. This is a **fee/meter reality
check** — "blind touch-and-hold loses a little after fees" — NOT a strategy verdict. Phase 0's
job was to prove the meter is trustworthy; it is. It says nothing about whether a *selective*
strategy has edge.

## 1. The strategy under test (ONE boring rule)

- **Primary fair value (A):** independent spot (Coinbase, already wired) + short realized-vol
  digital fair value for the contract's strike/expiry. One anchor only.
- **Signal:** trade a contract ONLY when the market price diverges from fair value by MORE than
  the round-trip cost (fee + spread). No edge over cost → no trade (reject).
- **Execution:** **maker-first** (resting limit); NO taker-at-50¢ default. Kalshi's postmortem
  showed taker fills at thin brackets are where the fee moat kills you.
- **Mode:** paper only. No leverage. No LLM in the pricing path. No live gate.

## 2. Metric & window

- **Metric:** mean net-of-cost EV per contract on OUT-OF-SAMPLE strategy settlements (fee + realistic
  maker fill modeled pessimistically; gross-only gates forbidden).
- **Emit:** each entry/hold/reject is an umbrella decision with `prediction.type = "prob"`,
  tagged as a **strategy** decision, kept SEPARATE from the 317 Phase-0 hypotheticals (do not let
  Phase-0 rows contaminate the strategy scoreboard — cf. the umbrella seed-exclusion discipline).
- **Window:** opens at the first counted strategy trade (stamp the date here when the build runs).
  Runs unattended until **KILL_N settlements** or **≥7 days**, whichever serves the window.

## 3. Pre-committed kill / verdict

- **KILL_N = 150** (hard minimum 100). No verdict of any kind before N ≥ 100.
- **FLOORED** if `net_ev_oos ≤ 0` at N ≥ KILL_N. Same spirit as kalshi weather — a floor is an
  honest win for the process, not a failure.
- **CONTINUE** (to Phase 2 loop gate) only if `net_ev_oos > 0` at N ≥ KILL_N.
- **INSUFFICIENT** is a legitimate dated outcome: N < 100 at window end → extend the SAME window
  (no new premise), or stop and record "not enough settlements," never "it's working."

## 4. On FLOORED — the pre-registered successor (avoids both traps)

If fair value A (spot + realized vol) FLOORS, the pre-committed next premise is **NOT** a re-run of
A. It is **fair value B: options-implied / IBIT risk-neutral digital** — a *structurally different*
input, and the roadmap's own "strongest named non-consensus anchor" (§2). Rationale, stated now so
it isn't rationalized later: realized vol is a **backward-looking point forecast**; if Kalshi BTC
digitals are priced off **implied** vol (which embeds forward-looking information RV lacks), then A
is the same class of miscalibration that floored kalshi weather ("a single point forecast can't
beat an informed counterparty"). A flooring on A therefore *advances* to B under its own fresh
pre-registration — it does not end btc-bot, and it does not silently re-test A.

*(Owner may instead elect to start Phase 1 directly on anchor B if the IBIT/Deribit data path is
solid — a stronger prior, at the cost of a harder data integration. A-first is the cheaper,
simpler baseline and is the default unless changed before the window opens.)*

## 5. Explicitly NOT in Phase 1

Leverage · self-improving loop / LLM brain · treating the 317 Phase-0 rows as alpha · live gate ·
gross-only scoring · any "edge" claim before KILL_N.

## 6. Result (appended at window end — do not edit above)

- **Runner deployed:** 2026-07-12 (`deploy/run_phase1.py` via launchd `com.btcbot.phase1_strategy`,
  120s loop, paper). Fail-closed: no trades until ≥20 evenly-spaced spot samples yield a
  *plausible* realized vol (10–300% annualized) — a guard added after a smoke test caught a
  degenerate seed producing a 3.46% vol and 52 phantom entries (purged; see LEDGER 2026-07-12).
- **Window opened:** _(stamp date at first counted strategy trade)_
- **Verdict:** _(pending — FLOORED / CONTINUE / INSUFFICIENT, with net_ev_oos and N)_
