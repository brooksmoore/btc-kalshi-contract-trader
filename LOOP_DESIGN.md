# LOOP_DESIGN.md — Self-Improving Loop for btc-bot

> Status: DESIGN / not yet built. Architecture for turning btc-bot into a
> self-improving quant loop, grounded in BTC short-term-contract research
> (June 2026) — NOT the generic loop-article template.
>
> Inherits the validated kalshi_bot_2.0 loop architecture (maker/checker split,
> pure-Python walk-forward gate, cheap-exit cost ordering, kill criterion). This
> doc only records what is **different for BTC**. See that project's LOOP_SPEC.md
> for the shared machinery; do not re-derive it.
>
> Scope: **paper only.** Never trades live, never moves money, never flips a
> live gate.

---

## 0. Why this bot is a better loop target than the weather bot — and the catch

The weather bot was a *known-dead* thesis (consensus NOAA; everyone prices the
same forecast). The loop confirmed it: FLOORED at −$0.023/contract.

BTC short-term contracts are different in a way that matters: there is a
**plausible non-consensus edge**, with a named source. So the loop here answers
an **open** question rather than confirming a closed one. That is the whole
reason it's worth building.

**The catch, stated up front (the v1/§4 trap, already present in this repo):**
the current backtest (`deploy/analyze_calibration.py`) scores trades against the
model's OWN price (`mp − threshold`, line ~215) and hardcoded 75¢/25¢ entries —
not real market prices. That is why it shows a 97% win rate and +$2,237 PnL.
**That number is a measurement artifact, not an edge** (the code says so itself:
"Entry prices are approximated — real market prices needed for live validation").
The loop must NOT be pointed at this data. Build-step 0 below fixes it.

---

## 1. Research grounding (what the design is built around)

From BTC short-term-contract research, June 2026:

1. **Edge source = options-implied fair value, not a vol guess.** The IBIT
   options chain provides an independent, professionally-calibrated probability
   that BTC is above a strike. When Kalshi's retail book diverges from that by
   more than costs, *that gap is the trade.* The current
   `orderbook_strategy.py` approximates fair value with a Black-Scholes digital
   on a **hardcoded 80% annual vol** (`BTC_ANNUAL_VOL = 0.80`) — a guess. The
   higher-quality fair-value anchor is the options surface. The loop should be
   allowed to test "options-implied vs BS-with-guessed-vol" as a leak.

2. **Costs are HIGHER here, and worst exactly where this strategy lives.**
   - Kalshi crypto carries an **above-base fee multiplier** (>0.07; assume the
     elevated value conservatively until confirmed from the live fee tier).
   - Fee `= round(multiplier × price × (1−price), 2)` is **maximized at 50¢** —
     and short-horizon BTC contracts cluster near 50/50 because the outcome is
     noise-dominated. So the strategy lives precisely where fees bite hardest.
   - There is ALSO a **settlement fee on the winning side** that the current
     model ignores entirely. The cost model MUST include it.
   - **Maker rebate ≈ zero fee; taker = 1–2¢/contract and dominant.** For a
     near-50¢ contract, taker fee alone can exceed any plausible micro-edge.
     **Maker-first execution is not optional — it is the strategy.**

3. **Edge (if any) is microstructure and decays fast.** Order-flow imbalance +
   short-window realized vol carry signal on a 15-min horizon; classical vol
   models add little. Signal at T-15min may be gone by T-5min (the bot already
   samples checkpoints — keep that). Verification must be walk-forward by TIME
   because microstructure regimes shift.

---

## 2. Build-step 0 — the prerequisite the loop cannot run without

**Real captured prices + real settlements.** Until these exist, every PnL number
is fiction and the loop's gate has nothing honest to score.

- At signal time, log the **real Kalshi best bid/ask** for the side the bot would
  trade — not `mp − threshold`, not a hardcoded 75¢. This is the single most
  important fix in the whole project.
- Run the bot in **paper against live BTC markets** so `trades.db` fills with
  real entry prices + real settlements (it is currently empty; the 5,638-contract
  "history" is simulated).
- Only then does the loop have a real out-of-sample signal. Pointing the loop at
  the current self-scored history would launder the §4 backtest trap through a
  fancier harness and emit a confident, wrong "GATE_OPEN."

Do not build the loop's maker/scheduler until step 0 has produced real settled
paper trades. (Same lesson the weather bot learned; more urgent here because the
fake number is more seductive.)

---

## 3. The cost model (BTC-specific — this is where edges live or die)

The checker's net-of-cost EV MUST deduct ALL of:

- **Taker fee** `round(CRYPTO_MULT × price × (1−price), 2)` per contract, using
  the crypto multiplier (conservative: assume elevated, confirm from live tier).
- **Settlement fee** on the winning side (currently ignored — add it).
- **Real spread**: enter at the real ask (taker) or model a real resting-limit
  fill (maker). No synthetic prices.

A change only counts as a closed leak if net-of-cost EV improves on held-out,
time-ordered real settlements by more than the holdout standard error
(t-stat ≥ 2.0, per the shared gate). Gross EV is irrelevant — at near-50¢, gross
is almost all fee.

---

## 4. The maker's leak taxonomy (btc-specific)

The maker hunts mechanical leaks, NOT alpha. The dominant ones here:

| Leak | Signal | Lever |
|---|---|---|
| **Taker fees on a maker-paid book** (the #1 leak — taker fee at 50¢ can exceed the edge) | net-of-cost EV << maker-hypothetical EV | shift to resting-limit / maker posture; reject signals only profitable as taker |
| **Wrong fair-value anchor** (BS-with-guessed-80%-vol vs options-implied) | model_prob systematically misses actual rate in a band | test options-implied fair value as the probability source |
| **Trading near 50/50 where fees max out** | low-edge near-strike contracts lose net of cost | raise the min net-of-cost edge gate; avoid the noise-dominated near-strike band unless edge clears costs |
| **Signal decay across checkpoints** | net-of-cost EV differs by `mins_before_expiry` | restrict entry to the horizon where edge survives costs |
| **Ignored settlement fee** | realized PnL < modeled PnL by a constant | add settlement fee to the cost model (a code fix, then a re-score) |

Routing rules (shared): software bugs → `src/`+tests, never the rulebook; noise
(no diagnosable mechanical cause / sub-sample) → recorded, not learned.

---

## 5. Cost efficiency (the loop's own spend)

Same posture as the weather loop — the fast thing is free, the expensive thing is
gated:

- **Price capture runs in the bot** (continuous, pure Python, ~$0). 15-min
  contracts settle many times/hour, so real data accumulates fast — the loop is
  NOT starved the way weather was, once step 0 is live.
- **The loop runs DAILY** over the day's accumulated real settlements — not
  per-contract. Cheap-exit prescan (pure-Python settlement count) gates the
  maker before any model call. Checker is pure Python, zero model calls.
- **Capable model (Sonnet-class) only on full-work days.** Estimate ~$2–3/month
  on Sonnet, same shape as the weather loop. The lever is unchanged: count real
  settlements BEFORE the maker reasons.

---

## 6. The kill criterion — and the honest pre-expectation

Shared mechanism: after `KILL_N` held-out **real** settlements, if best
achievable net-of-cost EV (every promoted leak-fix active) is still ≤ 0, declare
FLOORED and stop the maker.

**Honest pre-expectation, stated plainly:** unlike weather, this is a genuine
coin-flip. Short-term BTC microstructure edge is *plausible but unproven*, and
the research is clear it is hard and cost-sensitive — the crypto fee multiplier +
near-50¢ fee maximization is a real headwind that may eat any micro-edge. So:

- A **FLOORED** verdict here is a real finding (the edge doesn't survive crypto
  costs), delivered cheaply in paper.
- A **positive** net-of-cost floor here would be a genuinely earned result — not
  proof of the 97% backtest, but evidence that an options-anchored, maker-first,
  cost-honest version clears zero out-of-sample. THAT is the open question worth
  the loop. The live decision after that is yours alone, human-only.

The discipline that makes either answer trustworthy: real prices (step 0),
net-of-cost scoring (§3), walk-forward-by-time holdout, and a kill criterion that
stops the loop from iterating forever on a money-loser (the v1 §9.8 lesson).

---

## 7. Build order

0. **Real-price capture + paper run** (§2) — prerequisite. No loop until real
   settled trades exist.
1. **BTC cost model** (§3) — taker (crypto mult) + settlement fee + real spread.
   Unit-test against known fee examples.
2. **Net-of-cost scorer** over real settled paper trades (mirror the weather
   bot's `load_settled_*` + net EV).
3. **Checker (pure Python, no model)** — walk-forward-by-time gate; prove it
   rejects a deliberately bad change and passes a known-good one.
4. **Prescan + STATE_LOOP.md + change_log.jsonl + graveyard.**
5. **Maker** — leak diagnosis (§4) on the train window, ≤ MAX_PROPOSALS.
6. **Reversal monitor**, then **schedule** daily.

Metric of a healthy loop (shared): fraction of promoted changes that survive the
reversal monitor. Mostly-reverted = gate too loose. Mostly-stick = learning.

---

## 8. What this loop explicitly does NOT do

- Trade live, size live, or flip a live gate. Paper only.
- Score against the model's own price or any synthetic/hardcoded entry. Real
  captured prices only (the entire point of step 0).
- Treat the current 97%/+$2,237 backtest as evidence of edge. It is a
  self-scoring artifact (§0).
- Manufacture alpha. It closes mechanical leaks and tests whether a cost-honest,
  options-anchored, maker-first version clears zero. If it can't, it FLOORs.
- Iterate forever on a floored strategy (the v1 §9.8 trap).
