# Phase-1 kill-window scoreboard

**Generated:** 2026-07-16T20:15:31.452735Z
**Kill reference:** `EFFICACY_TEST_BTC_2026-07-11.md` (KILL_N=150, FLOOR if mean net ≤ 0)
**Contamination cutoff:** 2026-07-13T00:00:00Z (post phantom-edge fix only)

## Verdict

**FLOOR (mean ≤ 0)**

## Headline numbers (fee-honest, maker role)

| metric | value |
|--------|------:|
| N settled (post-fix) | 2425 |
| mean net EV / contract | -0.115060 |
| win % (gross > 0) | 0.91% |
| total net P&L | -279.020300 |
| total gross P&L | -275.020000 |
| total fees | 4.000300 |
| wins / losses | 22 / 2403 |
| unique tickers settled | 33 |
| entry_price median | 0.08 |
| entry_price mean | 0.1225 |
| share entry ≤ $0.05 | 0.4285 |

## Pipeline

- Post-fix Phase-1 entries logged: **6230**
- Settled: **2425**
- Still open (no market result yet): **3805**

## By side

| side | N | mean net | win% | total net |
|------|--:|---------:|-----:|----------:|
| no | 1217 | -0.135690 | 0.00% | -165.134600 |
| yes | 1208 | -0.094276 | 1.82% | -113.885700 |

## By TTE at entry (claimed filter: min 0.5 day)

| TTE bucket | N | mean net | win% | total net |
|------------|--:|---------:|-----:|----------:|
| 0.5–1d | 2425 | -0.115060 | 0.91% | -279.020300 |

## Penny-entry / residual phantom read

- Logged entries (post-fix)=6230 across ~33 unique tickers in the settled set — re-entry of the same market each cycle inflates N vs independent bets.
- Share of settled entries with entry_price ≤ $0.05: 42.9%. High share + cheap entry is the residual 'pick up pennies' signature even after the ≥5pp edge gate (cheap side of a large model/market disagreement).
- Settled mean net -0.115060/contract ≤ 0 after maker fees — this is the honest money-result direction for anchor A so far.
- No settled rows in the <0.5d TTE bucket — claimed min-TTE filter looks respected on the settled sample.
- Settlement PnL never uses p_fair; result comes from Kalshi market.result; fees from measurement.fees maker schedule.

---
_Measurement only. No live orders. Settlement truth from market result + independent
spot when available — never model p_fair. Fee model: measurement.fees (maker)._
