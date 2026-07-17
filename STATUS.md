# btc-bot — STATUS

> Standardized header. Keep these fields at the very top, always current.

- **One-liner:** Kalshi short-horizon BTC event-contract experiment — paper measurement first.
- **Stage:** **Phase 1 (Anchor A) RUNNING** + independent scoreboard. **Anchor B pricing engine OBSERVE-ONLY** (window CLOSED).
- **Live gate:** OFF — `paper_trade=True`; never places orders
- **Tests:** 51 green on runnable suite (`phase0` + `phase1_*` + `anchor_b_pricing` + quarantine live; 2 files skipped for pre-existing 3.8/numpy import issues)
- **Intelligence type:** Measurement only; no LLM in pricing path
- **Single most important next thing:** Anchor A window runs to **~2026-07-21** for honest independent N≥100 verdict. **Anchor B data path is wired observe-only** (`deploy/anchor_b_observe.py`) — Deribit RN digital works; N(d2)≈−dC/dK on live rows; **no counted `anchor_b` decisions**, window NOT open. Needs Brooks sign-off + A close before counted B.
- **Honest odds this makes money:** Low-to-moderate unproven. A independent mean still negative (N=33 so far). B untested as a strategy.
- **Last updated:** 2026-07-16 (legacy live runner quarantined; Phase-1 paper only)
- **Daemons:** `com.btcbot.phase0_capture`, `phase0_settle`, `phase1_strategy` — observe harness is **manual / launchd OFF**
- **Commands:**
  - Scoreboard: `python deploy/run_phase1_settlements.py && python deploy/phase1_scoreboard.py`
  - Anchor B observe: `python deploy/anchor_b_observe.py --once` → `data/anchor_b_observe.jsonl`

---

## Anchor B (pre-window)
| Item | Status |
|------|--------|
| Deribit → RN digital library | ✅ `measurement/anchor_b_pricing.py` |
| Unit tests | ✅ deep ITM/OTM/ATM, N(d2)≈BL, term interp, fail-closed |
| Observe harness | ✅ logs only; `mode=observe`, `phase=pre_window` |
| Counted decisions | ❌ none |
| Efficacy window | **CLOSED** |

## Phase 1 scoreboard (independent primary)
| metric | independent | raw (diagnostic) |
|--------|------------:|-----------------:|
| N | **33** | 2425 |
| mean net | **−0.048185** | −0.115060 |
| t-stat | **−0.90** | — |
| verdict | **INSUFFICIENT (N&lt;100)** | FLOOR (inflated) |

## Recent movement
- 2026-07-16 (later): **Legacy live channel quarantined.** `deploy/run_bot.py --env prod` without `--paper` hard-refuses (SystemExit 2; no `input()` confirm, no live Trader). `Trader(paper_trade=False)` requires env `BTC_LIVE_CONFIRM=ARM-REAL-MONEY`. Phase-1 paper path untouched. 5 new quarantine tests.
- 2026-07-16: Anchor B pricing engine + observe-only validation (window stays closed).
- 2026-07-16: Re-entry dedup; independent scoreboard primary.
- 2026-07-16: Scoreboard join; A interim reads.
- 2026-07-15: phase0_capture re-bootstrap after STALE.
- 2026-07-13: phantom-edge gates.
