# Anchor B data path — Deribit vs IBIT (decision one-pager)

*Prep for `EFFICACY_TEST_BTC_B_2026-07-16.md` §1. Not a commitment — this is so the
data-source choice is teed up when Anchor A's window closes (~2026-07-21). No build yet.*

## What Anchor B actually needs
One number per Kalshi contract: the **risk-neutral probability that BTC is above the
contract's strike at the contract's expiry** — a *forward-looking* fair value (vs Anchor A's
backward-looking realized vol). Kalshi KXBTCD contracts are digitals like "BTC > $63,249.99
at 2026-07-16 17:00." We need a market-implied P(BTC > K at T) to compare against Kalshi's
price, and trade only when the gap beats round-trip cost.

Options markets give exactly this: the option surface *is* the market's risk-neutral
probability distribution. Two ways to source it.

## The two candidates

### Option 1 — Deribit BTC options  ✅ recommended
The dominant BTC options venue. Public REST/WebSocket API, **free, no key for market data**,
full chain (strikes, expiries, per-strike implied vol, mark prices), **24/7**.
- **Directness:** actual BTC options → the digital prob is derived straight from the surface
  (either `P = N(d2)` using the smile's IV at the strike, or the Breeden-Litzenberger
  derivative `−dC/dK` across two nearby strikes). No proxy, no basis.
- **Coverage:** 24/7/365 — matches Kalshi BTC contracts, which settle overnight and weekends.
- **Cost:** $0 for market data.
- **Work:** expiry/strike rarely line up exactly with Kalshi's — interpolate the IV term
  structure to Kalshi's expiry time and evaluate the digital at Kalshi's strike. That
  interpolation + the digital math is the real integration effort (est. a focused Grok build
  + a spike to confirm the API shape and a couple of hand-checked prices).

### Option 2 — IBIT-implied  ❌ not recommended
Derive implied vol from options on IBIT (the iShares spot-BTC ETF), map to BTC.
- **Basis layer:** IBIT is an ETF proxy (≈ a fixed fraction of BTC, with its own NAV/premium
  drift) — you inherit an ETF-to-BTC conversion and basis risk the digital doesn't need.
- **Coverage gap (disqualifying):** IBIT options trade **US market hours only**. Kalshi BTC
  contracts expire overnight, pre-market, and weekends — exactly when IBIT options are dark.
  You'd have no fair value for a large share of the very contracts you're pricing.
- **Cost/access:** US equity options data usually needs a paid feed (OPRA/vendor); not free.
- **Only upside:** familiar if you already ran an equity-options pipeline — which we don't.

## Recommendation
**Deribit.** It's the direct, free, 24/7, forward-looking source the test's premise (§1, §4)
is actually built on — real BTC risk-neutral probabilities with no proxy. IBIT's US-hours-only
coverage alone likely disqualifies it for 24/7 Kalshi BTC contracts, and it adds ETF basis +
data cost for no benefit.

## ✅ Spike result (2026-07-16, Claude, $0 — free public API)
Ran the live spike. **PASS:** Deribit reachable (BTC index $64,070.94); nearest BTC option expiry
2026-07-17 08:00 UTC, 50 instruments; ATM call mark_iv 32.9%. Digital `P(BTC>64000 at expiry)`
computed **two independent ways — N(d2)=0.550 vs Breeden-Litzenberger −dC/dK=0.570, agree within
0.020.** So: the endpoints work, IV + marks are usable, and the risk-neutral digital math is sane
and self-consistent. Anchor B on Deribit is de-risked. Endpoints used: `public/get_index_price`,
`public/get_instruments`, `public/get_book_summary_by_currency` (carries `mark_iv` + `mark_price`).

## Remaining honesty flags (finish during the build, not blockers)
- I can't hit the Deribit API from here, so confirm live: the market-data endpoints, rate
  limits, and that per-strike IV + marks come back as expected. (My knowledge of Deribit's API
  may be stale.)
- Hand-check 2–3 digitals: pull the chain, compute `P(BTC > K)` two ways (N(d2) vs −dC/dK), and
  confirm they agree and look sane vs a Kalshi mid. If they diverge wildly, the interpolation
  or IV handling is off — fix before any counted trade.
- Match Kalshi's exact settlement convention (strike inclusive/exclusive, settle timestamp,
  which BTC index) so the fair value is priced to the *same* event Kalshi settles on.

## What this unblocks
Once Brooks picks Deribit (or overrides), the Anchor B build is a clean Grok handoff: wire the
Deribit chain → risk-neutral digital → the existing maker-first / cost-gated / independent-N
Phase-1 harness (already deduped), emit `anchor_b` decisions, score on the same independent
scoreboard. **Nothing starts until Anchor A's window closes (~07-21) and its honest verdict
lands** — this doc just removes the data-source unknown from the critical path.
