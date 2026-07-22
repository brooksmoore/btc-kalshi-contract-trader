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
| Backfill span / N per horizon | — |
| Best horizon: model Brier / market Brier | — |
| Gate PASS? | — |
| Coinbase−floor_strike basis (mean/sd) | — |
| **Verdict** | — |
| Next step | — |

---
_Retrospective, paper, $0. No orders. Does not open S2 or touch the daily lane._
