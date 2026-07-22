# Efficacy Test — btc 15m RETRO calibration (accelerated M3 gate)

*Pre-registered 2026-07-22, BEFORE the historical backfill is scored. Thresholds frozen. This test
answers ONE of S2's three locks — model calibration — retrospectively, in days instead of waiting
for 30 forward resolves. It does NOT open S2 (fill-honest P&L + Brooks's yes remain). Append §6 only.*

## 0. Scope
- Accelerates the **M3 calibration gate** (signal-quality question → backtestable). Reuses the shipped
  `measurement/m15_calibration.calibration_gate` thresholds verbatim.
- Does NOT accelerate: fill-honest P&L (execution realism, forward-bound) or the in-session yes.
- Handoff: `umbrella/inbox/CLAUDE_TO_GROK_btc_15m_retro_calibration_HANDOFF.md`.

## 1. Thesis (falsifiable)
The Coinbase-spot-driven `p_fair` (K = Kalshi `floor_strike`) is at least as calibrated as the market
mid on historical settled KXBTC15M outcomes — i.e. worth spending forward fill-honest time on.

## 2. Method (frozen)
- Universe: settled `KXBTC15M-*` markets over the backfilled span; one row per market at horizons
  **T-1min / T-2min / T-5min** before close.
- `spot_now` = point-in-time Coinbase 1-min spot as-of T-k (NO leakage). K = `floor_strike`. Vol =
  `m15_vol` on trailing as-of window. `p_fair` = `price_m15_market`.
- Label = Kalshi `result`. Market baseline = last pre-close mid.
- Score via the shipped `calibration_gate()` — unchanged thresholds: **N≥30, model Brier ≤ market
  Brier + 0.02 slack, absolute floor 0.28.**

## 3. N floor (frozen)
- Per horizon: need **N≥30** settled matched rows (the gate's own min). Expect hundreds (dense product).
- If <30 rows backfillable at every horizon → **INSUFFICIENT** (Kalshi history too thin; forward is
  the only calibration path — a fast, valid answer).

## 4. Pre-committed verdict (frozen — Claude computes)
| Verdict | Condition (best horizon that meets N≥30) |
|---------|------------------------------------------|
| **CALIBRATED → worth the forward window** | `calibration_gate` PASS: model Brier ≤ market Brier + 0.02 AND ≤ 0.28 abs |
| **MISCALIBRATED → fix model first** | gate FAIL. Prime suspect = Coinbase-vs-BRTI basis (see §5); de-bias and re-run BEFORE any forward S2 spend |
| **INSUFFICIENT** | <30 backfillable rows at every horizon |

## 5. Mandatory diagnostic
Report the distribution of `(coinbase_spot_at_open − floor_strike)`. A persistent non-zero offset is
the basis I flagged in the eligibility re-audit; if MISCALIBRATED, this is the first thing to correct
(measure spot against a BRTI-consistent reference, or de-bias `spot_now`).

## 6. Result (append only after scoring)
| Field | Value |
|-------|-------|
| Backfill span / N per horizon | 2026-07-17 → 07-22 (5 days, dense) · t1 N=347 / t2 N=408 / t5 N=451 |
| Best horizon: model Brier / market Brier | **t2: 0.0528 model vs 0.0649 market** (model genuinely better) |
| Gate PASS? | **t1 FAIL** (mkt 0.027 too sharp near close) · **t2 PASS** · **t5 PASS** (0.108 vs 0.107, slack) |
| Coinbase−floor_strike basis (mean/sd) | **−$6.37 / $30.69** (persistent ~$6 under-floor, fat tails ±$40); uncorrected |
| **Verdict** | **🟢 CALIBRATED** (≥1 horizon meets N≥30 + gate PASS; t2 genuinely, t5 within slack) |
| Next step | Removes the CALIBRATION lock of S2. Forward fill-honest P&L + Brooks yes remain. |

### Verdict rationale (CALIBRATED — one of S2's three locks now cleared)
- Per the frozen rule, the model clears the shipped `calibration_gate` at t2 (genuinely beats the
  market) and t5 (within the 0.02 slack), both far above N≥30. → **CALIBRATED.** The model is worth
  spending forward fill-honest time on. This is the first "the model isn't broken" evidence in the
  15m lane, delivered in days by the retro accelerate.
- **Honest caveats (do NOT read this as "proven"):**
  1. **t1 FAILS** — 1 min before close the market is near-perfectly informed (Brier 0.027); the GBM
     can't compete. **Usable horizon is t2–t5, not the final minute** — any forward S2 rests should
     carry ≥2 min TTE, never the last minute.
  2. **t5 is a slack-pass** (model marginally *worse* than market, inside tolerance); the genuine
     edge is at **t2**. Don't oversell t5.
  3. **5 days / one BTC regime.** N is high because the product is dense (96/day), but this is a
     single week's volatility regime. CALIBRATED ≠ regime-robust. Re-run after a different regime,
     or treat forward as the regime test.
  4. **~$6 Coinbase-vs-BRTI basis is uncorrected** — the model PASSES despite it, so de-biasing is
     upside; do it before/during forward S2 (measure spot against a BRTI-consistent reference).
- **Scope reminder:** CALIBRATED does NOT open S2. It clears 1 of 3 locks. The fill-honest P&L
  (execution realism — forward-bound, un-accelerable) and Brooks's in-session yes remain.

---
_Retrospective, paper, $0. No orders. Does not open S2 or touch the daily lane._
