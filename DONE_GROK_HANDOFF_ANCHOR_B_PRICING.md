# GROK_HANDOFF — Anchor B pricing engine + observe-only validation (parallel work; window stays CLOSED)

**To:** Grok Build · **From:** Claude (auditor) · **Date:** 2026-07-16
**Status:** DONE 2026-07-16 — paper/observe-only. **Does NOT open the Anchor-B efficacy window** — that needs
Brooks's sign-off AND Anchor A's real verdict at close (~2026-07-21). This is the reusable
pricing library + offline/observe validation, so B can flip on the instant A floors.

## Why this is safe to build now (not premature)
Anchor A is running to window close; its verdict lands ~07-21. Building B's *pricing engine* and
validating it OBSERVE-ONLY (like Phase 0 was for A) contaminates nothing and violates no
pre-registration — as long as **no counted `anchor_b` trades are emitted** and the window is not
declared open. If A somehow does not floor (very unlikely, t=−0.90), the engine is still reusable.

## Spike already de-risked the data path (Claude, 2026-07-16, $0)
Deribit public API works. `P(BTC>K at expiry)` computed two ways agrees within 0.02 (N(d2) vs
−dC/dK). Endpoints: `public/get_index_price?index_name=btc_usd`,
`public/get_instruments?currency=BTC&kind=option&expired=false`,
`public/get_book_summary_by_currency?currency=BTC&kind=option` (carries `mark_iv`, `mark_price`
in BTC). See `ANCHOR_B_DATA_PATH.md` §Spike result. Build on those.

## Task
1. **Pricing library** (`measurement/anchor_b_pricing.py`): given a Kalshi KXBTCD contract
   (strike K, expiry timestamp T, above/below), return the Deribit-implied risk-neutral
   `P(BTC {>,<} K at T)`.
   - Pull the Deribit BTC option chain + per-strike `mark_iv` + index price.
   - **Interpolate the IV term structure to Kalshi's T** (Kalshi expiries rarely match Deribit's
     08:00-UTC expiries) and the smile to Kalshi's K.
   - Compute the digital primarily via `N(d2)` (r=0 crypto convention); ALSO compute the
     Breeden–Litzenberger `−dC/dK` cross-check and **flag if the two disagree by >0.08** (the
     spike showed 0.02 — a large gap means the interpolation/IV handling is off).
   - Match Kalshi's exact settlement convention (strike inclusive/exclusive, settle timestamp,
     which BTC index Kalshi settles on) so B prices the SAME event Kalshi settles.
2. **Fail-before unit tests** (`tests/test_anchor_b_pricing.py`):
   - Deep ITM digital → ~1.0, deep OTM → ~0.0, ATM → ~0.5 (fails against a stub/None impl).
   - N(d2) and −dC/dK agree within tolerance on a synthetic flat-vol chain.
   - A term-structure interpolation test: T between two Deribit expiries returns a value between
     the two anchors, not an extrapolation blowup.
   - Fail-closed: missing/stale Deribit data → returns None + logged, never a fabricated prob.
3. **Observe-only harness** (`deploy/anchor_b_observe.py`, launchd OFF by default): for each live
   KXBTCD contract, log `{ts, ticker, K, T, kalshi_mid, anchor_b_prob, gap, would_trade}` to
   `data/anchor_b_observe.jsonl`. **Tag every row `mode:"observe"` / `phase:"pre_window"`. Emit
   NO umbrella `anchor_b` counted decisions. Do NOT open the window.** This is the Phase-0-equivalent
   sanity feed for B — proves the fair value tracks Kalshi sensibly before a single counted bet.

## Definition of done
- [ ] Fail-before outputs captured, then green; existing btc tests still pass.
- [ ] One real observe run: paste ~5 rows of `anchor_b_observe.jsonl` (contract, kalshi_mid,
      anchor_b_prob, gap) + confirm N(d2) vs −dC/dK agree on live data.
- [ ] `EFFICACY_TEST_BTC_B_2026-07-16.md` §7 "Data path (B) wired" → note it's built + observe-validated,
      **window still CLOSED pending Brooks sign-off + A's verdict.**
- [ ] STATUS.md + LEDGER.md updated.

Do NOT: open the Anchor-B window, emit counted `anchor_b` decisions, touch live/real orders, add
LLM to the pricing path, or wire this into the counted Phase-1 trading loop. That integration is a
SEPARATE handoff after A's verdict + Brooks's go.

Report to `../umbrella/inbox/GROK_TO_CLAUDE_anchor_b_pricing_RESULTS.md`; rename `DONE_` when complete.
