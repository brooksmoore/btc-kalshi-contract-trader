# GROK_HANDOFF — Phase-1 kill-window scoreboard (measure, don't invent edge)

**To:** Grok Build · **From:** Claude (auditor) · **Date:** 2026-07-16
**Status:** DONE 2026-07-16 — paper-only measurement. No live flips, no LLM spend, no strategy changes.

## Why now
Phase 1 is generating real paper N, but it is **unscored** — the pre-registered kill
(`EFFICACY_TEST_BTC_2026-07-11`: KILL_N≈150, FLOOR if mean net EV OOS ≤ 0) cannot be
evaluated because Phase-1 entries are not joined to settlements. Build the join + a
one-page scoreboard so the experiment we started can reach a falsifiable verdict.

## Verified data facts (Claude checked these 2026-07-16 — build on them, re-verify)
- `data/phase1_positions.jsonl` — **6,230 entries**, ALL dated ≥ 2026-07-13 (post
  phantom-fix; clean of the pre-fix junk). Fields per row: `ts, ticker, side,
  entry_price, p_fair, net_ev, decision_id`.
- `data/settlements.jsonl` — 725 rows, BUT they are all `phase: "0"`, `role: "taker"`,
  `decision_id` like `btc:capture:...` — i.e. **Phase-0 capture settlements, NOT Phase-1.**
  Fields: `ts, ticker, decision_id, side, role, contracts, entry_price,
  entry_price_source, result, spot_at_entry, spot_at_settle, gross_pnl, fees, net_pnl,
  phase, extra`.
- `trades.db` is EMPTY (0 rows) — Phase-1 does not write there; ignore it.
- **So today: 0 Phase-1 entries are settled/scored.** The join does not exist yet — that
  is the gap.
- Baseline signal: the 725 Phase-0 settlements run **mean net −$0.0071/contract, 8.6%
  win** — the book is hard to beat. Phase-1 must clear THAT bar after fees to be edge.

## ⚠️ The finding to surface (not just plumbing)
6,230 entries in ~2 days is NOT "rare ≥5pp multi-day disagreements." The samples are
penny-entries on near-certain contracts (e.g. buy `no` @ $0.02 when p_fair=0.86). This
looks structurally like the phantom-edge "pick up pennies" pattern the STATUS says was
fixed. **The scoreboard's job is to tell us which it is:** genuine edge, or thousands of
penny-entries that floor after fees. Report the number; do not code to make it look good.

## Task (smallest steps; measurement only)
1. **Settle Phase-1 entries.** Extend the settlement path so Phase-1 `phase1_positions`
   entries get joined to their contract outcome (spot_at_settle vs the contract's strike/
   side) and written to a Phase-1 settlement store (`data/phase1_settlements.jsonl`) with
   the SAME fee-honest fields the Phase-0 settlements use (gross_pnl, fees, net_pnl). Reuse
   `measurement/settlement.py` + `measurement/fees.py`; do not reinvent the fee model.
   Key entries→settlement on `decision_id`.
2. **Score only post-fix, non-contaminated entries.** All 6,230 are already ≥07-13, but
   assert it in code (drop anything earlier) so the kill window can never be polluted.
3. **One-page scoreboard** (`deploy/phase1_scoreboard.py` → writes
   `PHASE1_SCOREBOARD.md`): N settled, mean net EV/contract after fees, win%, total net
   P&L, and the verdict line vs the pre-registered kill — `FLOOR (mean ≤ 0)` /
   `edge candidate (mean > 0, N<150 keep going)` / `PASS (mean > 0 at N≥150 across ≥2
   regimes)`. Include a breakdown by contract TTE bucket (the ≥0.5-day min-TTE gate is a
   claimed filter — show whether entries respect it).
4. **No self-scoring contamination.** Honor `measurement/self_score_guard.py` — settlement
   truth must come from independent spot, never the model's own p_fair.

## Fail-before tests (per repo discipline)
- A synthetic entry that settles a loss must show net_pnl = −(entry_price+fees), not 0
  (proves fees are applied and direction is right) — fails against no-join code.
- The scoreboard's kill verdict must read FLOOR on a synthetic set whose mean net ≤ 0, and
  edge-candidate on mean > 0 — one test each, provably failing pre-build.
- A pre-07-13 entry must be EXCLUDED from the scored set (contamination guard).

## Definition of done
- [ ] Fail-before outputs captured, then green; existing 11 Phase-0 tests still pass.
- [ ] One real run: paste `PHASE1_SCOREBOARD.md` — N, mean net EV after fees, win%, vs-kill
      verdict, TTE breakdown. This is the deliverable Brooks actually wants: a dated,
      falsifiable money-result read on Phase 1.
- [ ] Honest note on the penny-entry question: are the 6,230 real ≥5pp disagreements or a
      residual pennies pattern? Back it with the settled numbers.
- [ ] STATUS.md + LEDGER.md updated.

Do NOT: open the loop gate, spend LLM budget, touch the live path, or pick successor
anchor B — that's pre-committed for AFTER a floor/edge verdict, not now.

Report to `../umbrella/inbox/GROK_TO_CLAUDE_phase1_scoreboard_RESULTS.md`; rename this
file `DONE_` when complete.
