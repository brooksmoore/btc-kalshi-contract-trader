# Phase-1 kill-window scoreboard

**Generated:** 2026-07-16T20:33:29.917882Z
**Kill reference:** `EFFICACY_TEST_BTC_2026-07-11.md` (KILL_N=150, FLOOR if mean net ≤ 0)
**Contamination cutoff:** 2026-07-13T00:00:00Z (post phantom-edge fix only)
**Primary unit:** **independent** bets (one per ticker / entry-event; cycle re-logs collapsed)

## Verdict (independent)

**INSUFFICIENT (mean ≤ 0, N=33<100 — keep settling; not a final floor yet)**

## Headline numbers — independent (primary)

| metric | value |
|--------|------:|
| N independent (unique tickers) | 33 |
| raw cycle settlements (inflated) | 2425 |
| mean net EV / bet | -0.048185 |
| t-stat (mean vs 0) | -0.8979 |
| win % (gross > 0) | 9.09% |
| total net P&L | -1.590100 |
| total gross P&L | -1.530000 |
| total fees | 0.060100 |
| wins / losses | 3 / 30 |
| unique tickers | 33 |
| entry_price median | 0.11 |
| entry_price mean | 0.1373 |
| share entry ≤ $0.05 | 0.3939 |

## Raw cycle settlements (legacy / diagnostic only)

| N raw | 2425 |
| mean net (raw) | -0.115060 |
| win % (raw) | 0.91% |
| verdict if scored raw | FLOOR (mean ≤ 0) |

_Raw N is inflated by re-logging the same open contract every cycle. Do not use for kill._

## Pipeline

- Post-fix Phase-1 entries logged (raw): **6230**
- Settled independent / raw: **33** / **2425**
- Still open decision_ids (no market result yet): **3805**

## By side (independent)

| side | N | mean net | win% | total net |
|------|--:|---------:|-----:|----------:|
| no | 15 | -0.131067 | 0.00% | -1.966000 |
| yes | 18 | 0.020883 | 16.67% | 0.375900 |

## By TTE at entry (independent; claimed filter: min 0.5 day)

| TTE bucket | N | mean net | win% | total net |
|------------|--:|---------:|-----:|----------:|
| 0.5–1d | 33 | -0.048185 | 9.09% | -1.590100 |

## Notes

- Dedup: raw cycle settlements=2425 → independent N=33 (inflation ×73.5). Primary kill uses independent only.
- Logged raw entries (post-fix)=6230. Going forward the runner logs at most one open position per ticker.
- Share of independent entries with entry_price ≤ $0.05: 39.4%.
- Independent mean net -0.048185/bet ≤ 0 after maker fees, t=-0.8979 — honest money-result direction for anchor A.
- Settlement PnL never uses p_fair; result from Kalshi market.result; fees from measurement.fees maker schedule.

---
_Measurement only. No live orders. Settlement truth from market result + independent
spot when available — never model p_fair. Fee model: measurement.fees (maker)._
_Primary N = independent bets (one per ticker). Anchor B inherits this unit._
