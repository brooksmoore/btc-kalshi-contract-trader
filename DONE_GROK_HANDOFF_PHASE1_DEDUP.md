# GROK_HANDOFF — Fix Phase-1 re-entry/re-logging (measurement integrity)

**To:** Grok Build · **From:** Claude (auditor) · **Date:** 2026-07-16
**Status:** DONE 2026-07-16 — paper-only measurement integrity fix. No live, no LLM, no strategy retune.
**Blocks:** Anchor B's efficacy window cannot open until this is verified
(`EFFICACY_TEST_BTC_B_2026-07-16.md` §0).

## The bug (verified)
Your own scoreboard surfaced it: Anchor A logged **2,425 "settlements" from only 33 unique
markets** — the Phase-1 loop re-enters/re-logs the SAME contract every ~120s while it stays open.
Effects:
1. **Inflates N ~73×** — the pre-registered KILL_N (150) was hit on pseudo-replicated rows, not
   independent bets. On the 33 independent markets the mean is −$0.048 with a CI that crosses zero.
2. **Would be a real trading bug live** — re-entering the same position 73× is not a strategy, it's
   a loop artifact.
3. **Corrupts Anchor B before it starts** — B's scoreboard inherits the same inflation unless fixed.

## The fix (smallest change; measurement only)
1. **One counted entry per (ticker) per genuine new signal.** While a contract has an open counted
   position (or was entered this window), the loop must NOT log a new entry for it every cycle.
   Track open positions by `ticker` (or `decision_id` root) and skip re-entry until it settles.
   The signal must genuinely change to justify a new bet — a still-standing divergence on an already-
   held contract is the SAME bet, not a new one.
2. **`ts` on entries stays** (fine for audit), but the SETTLEMENT/scoreboard unit becomes the
   independent bet: one settled row per market per entry event, not one per cycle.
3. **Backfill flag, don't rewrite history:** leave the existing inflated Anchor-A rows in place
   (the verdict is already stamped) but have `phase1_scoreboard.py` compute BOTH raw and
   `--independent` (dedup to one bet per ticker per entry event) and show the independent number as
   primary going forward. Anchor B scores on independent only.

## Fail-before tests (per repo discipline)
- A test feeding the same open contract across 5 consecutive cycles asserts **exactly 1** counted
  entry is logged (fails against current re-logging code).
- A test asserting the scoreboard's `--independent` N equals the unique (ticker, entry-event) count,
  not the raw cycle count.
- A test that a genuinely new signal on a DIFFERENT strike DOES log a new bet (don't over-suppress).

## Definition of done
- [ ] Fail-before outputs captured, then green; existing 34 tests still pass.
- [ ] One real run over recent data: paste the independent-N scoreboard (N, mean net EV, t-stat,
      win%). Confirm independent N now tracks unique markets, not cycles.
- [ ] `EFFICACY_TEST_BTC_B_2026-07-16.md` §0/§7 line updated to "fixed & verified" with the proof.
- [ ] STATUS.md + LEDGER.md updated.

Do NOT: open the Anchor-B window (that's Brooks's sign-off after this + the B data path), touch
live, spend LLM, or rewrite the stamped Anchor-A verdict.

Report to `../umbrella/inbox/GROK_TO_CLAUDE_phase1_dedup_RESULTS.md`; rename this file `DONE_` when complete.
