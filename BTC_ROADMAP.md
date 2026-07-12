# BTC short-contract experiment — Roadmap (umbrella-aligned)

**Owner:** Brooks · **Builder:** Grok · **Auditor:** Claude  
**Born:** 2026-07-10  
**Scope:** paper only until a human flips a live gate. No leverage until net-of-cost edge is proven.  
**Prior art:** `LOOP_DESIGN.md` (this repo) · kalshi_2.0 FLOORED weather thesis · `umbrella/GROK_HANDOFF_LOOP_GATE.md` (unbuilt until consumer ready)

---

## 0. Mission (one sentence)

Answer, honestly and cheaply: **does a cost-honest, maker-first BTC short-horizon Kalshi strategy clear zero net-of-cost EV out-of-sample on real prices** — yes → consider small paper scale; no → FLOORED and stop.

This is **not** “self-improve until profitable.” The loop’s job is to **measure and kill lies**, not manufacture alpha.

---

## 1. Research brief (2026-07-10) — what the literature and fee schedule imply

### 1.1 Venue & product
- Kalshi lists **BTC event contracts** (price brackets / timed “above X by time T”). Settlement for crypto event products is typically tied to **regulated index/RTI-style benchmarks** (CF Benchmarks-class settlement is industry practice on Kalshi crypto); treat **settlement source as sacred** and log it.
- Product family includes short windows (bot targets **~5–15 min** style markets). Liquidity and microstructure **vary by session** (US vs Asia hours are different regimes — do not pool blindly in backtests).

### 1.2 Fees (load-bearing — edge lives or dies here)
Public Kalshi fee schedule pattern (confirm live series multiplier before trusting any EV):

| Role | Formula shape | Implication |
|------|----------------|-------------|
| **Taker** | ~`0.07 × C × P × (1−P)` (series may use a **higher crypto multiplier**) | Fees **peak at P=0.50** — exactly where short BTC noise markets trade |
| **Maker** | ~¼ of taker shape (e.g. ~0.0175×…) | **Maker-first is not optional** |
| **Settlement** | Official schedule often **no settlement fee** (re-verify series notes) | Still model **spread + adverse selection**; do not invent phantom settlement fees |

**Worked example (standard taker mult 0.07, 1 contract at 50¢):**  
fee ≈ `0.07 × 0.5 × 0.5 = $0.0175` ≈ **1.75¢** — already larger than a **1¢ “edge”**. At 100 contracts near 50/50, taker drag is brutal.

**Research consensus (prediction-market practitioners):**
- Makers tend to do better than takers on average; pure market-taking is often negative EV after fees.
- Near-50¢ markets are where fee drag is worst; selective 60–80¢ / extreme books can be fee-efficient but **low edge frequency**.
- Crypto books can **lag spot by seconds** — plausible microstructure edge, **not free money**; latency and fill reality eat naive backtests.

### 1.3 Fair-value anchors (the open question)
| Anchor | Quality | Notes |
|--------|---------|--------|
| Model’s own mid / hardcoded 75–25¢ | **Invalid** | Current 97% win-rate artifact |
| Black–Scholes digital + **guessed** 80% vol | Weak | Current `orderbook_strategy` default |
| **Spot + realized short-horizon vol** | Medium | Independent of Kalshi book |
| **IBIT (or BTC) options-implied digital / RN density** | Strongest **named** non-consensus | Literature: prediction markets vs options can show multi-pp wedges; options are risk-neutral, not pure physical prob — still a **disciplined external** check |
| Pure lag vs Coinbase/Binance mid | Microstructure | Needs low latency; regime-dependent |

We **pre-register** which anchor is primary for the first efficacy test (recommend: **spot+realized vol OR options-implied**, not both until step-0 is green).

### 1.4 Leverage
- Out of scope for phases 0–3. Leverage multiplies fee drag and measurement error.  
- Only reconsider after **net-of-cost EV > 0** on held-out paper with KILL_N met — and only as an explicit human decision.

### 1.5 What we will **not** treat as evidence
- Old 97% / +$2237 backtest  
- Empty `trades.db` “paper” with synthetic entries  
- Reddit/X 15m BTC dashboards without fee+latency model  
- Weather-Kalshi loop results (different premise; harness reusable, thesis not)

---

## 2. Non-negotiables

1. **Paper only** until Brooks explicitly arms a live gate.  
2. **Step-0 green** before any strategy claim or self-improvement loop.  
3. **Net-of-cost** scoring only (taker/maker fee + realistic fill; no gross-only gates).  
4. **Real Kalshi bid/ask at decision time** logged forever.  
5. **Independent BTC reference price** (not derived from the bot’s fair-value model alone).  
6. **Pre-registered kill** before the evaluation window starts (date it).  
7. **Umbrella:** decisions + snapshots emit; findings may stay INSUFFICIENT for a long time — that is success of honesty.  
8. **No leverage** in phases 0–3.

---

## 3. Phased roadmap

### Phase 0 — Measurement membrane for BTC (BLOCKING)  
**Goal:** honest data plane. No alpha claims.

| Deliverable | Done when |
|-------------|-----------|
| **0.1 Independent spot feed** | BTC USD mid from a public source (e.g. Coinbase/Kraken/Yahoo or exchange REST), timestamped, fail-closed on stale |
| **0.2 Kalshi market capture** | For open BTC series: ticker, strike/window, best bid/ask, mid, volume if available, capture_ts |
| **0.3 Decision log** | Every paper intent → `decisions.ndjson` (umbrella schema) with `ref_price` = **tradeable** side (ask for buys), prediction type `prob` or `none` |
| **0.4 Settlement recorder** | Outcome vs independent settlement rule; write `outcomes` / trades.db with **real** entry + settle |
| **0.5 Fee model module** | Pure functions: taker/maker fee given P, C, series multiplier; unit tests vs fee schedule examples |
| **0.6 Artifact kill** | Gate test: any path that scores against model-own price **fails** CI |
| **0.7 Empty honest scoreboard** | Dashboard/STATUS: N=0 until real settlements; never show 97% |

**Exit gate Phase 0:** ≥ **50** paper settlements with real entry bid/ask + independent spot stamp + fee fields populated. (Not enough to declare edge — enough to trust the meter.)

**Estimate:** 1–3 focused sessions. **Do not skip.**

---

### Phase 1 — Cost-honest baseline strategy (no loop yet)  
**Goal:** one boring champion under the meter.

| Deliverable | Done when |
|-------------|-----------|
| **1.1 Primary fair value** | Choose **one** primary: (A) spot+short RV digital, or (B) options-implied digital if IBIT data path is solid |
| **1.2 Edge rule** | Trade only if `edge_net = f(fair) − book − fees − spread_model ≥ MIN_NET_EDGE` |
| **1.3 Maker-first** | Default resting limit; taker only if pre-registered exception (probably **never** in v1) |
| **1.4 Regime filters** | Optional: skip first N minutes after open, skip low-liquidity, skip pure 48–52¢ unless edge clears 2× fee |
| **1.5 Pre-register efficacy test** | Dated document: metric = mean net EV/contract; **KILL_N ≥ 100** (prefer 150–200); FLOORED if net_ev_oos ≤ 0; t-bar optional |

**Exit gate Phase 1:** paper runner runs unattended ≥ **7 days** or **KILL_N** settlements (whichever first for the *window*), with umbrella N growing from real `prob` decisions.

---

### Phase 2 — Shared loop gate as consumer (harvest kalshi organs)  
**Goal:** self-improvement of **mechanical leaks only**, not free-form LLM alpha.

| Deliverable | Done when |
|-------------|-----------|
| **2.1** Port/implement `umbrella_core.loop` (pluggable metric) — first real consumer = btc paper scorer |
| **2.2** Graveyard seed: weather FLOORED + BTC dead knobs (hardcoded vol-only, model-self-score, taker-at-50¢, etc.) |
| **2.3** Leak menu only: maker vs taker, min edge, strike band, checkpoint timing, fair-value A vs B |
| **2.4** Reversal monitor + thrash guard |

**Exit gate Phase 2:** either **FLOORED** (honest win for the process) or **net_ev_oos > 0** with holdout N ≥ KILL_N and reversal-stable for ≥ REVERT_PATIENCE cycles.

---

### Phase 3 — Optional sophistication (only if Phase 2 is green)  
- Options surface as **challenger** fair value (if not already primary)  
- Multi-signal ensemble **as challenger**, not automatic promotion  
- Session-of-day models  
- **Still paper**; still no leverage  

### Phase 4 — Human-only live decision  
- Not automatic. Requires: Phase 2 green + Claude audit of receipts + Brooks explicit live gate  
- Size: tiny; leverage: still no unless separate written test  

---

## 4. Pre-registered kill criteria (draft — lock before Phase 1 window)

| Item | Draft value | Notes |
|------|-------------|--------|
| Metric | Mean **net** EV per contract (USD) | After fees + modeled spread |
| Min OOS N | **150** first-per-market settlements | Prefer time-ordered holdout |
| FLOORED | net_ev_oos ≤ 0 at N ≥ KILL_N | Same spirit as kalshi weather |
| Promote change | Δ net EV > 0 with t ≥ 2 on holdout | Loop only |
| Max paper bankroll | e.g. **$50–100** demo | Cap attention, not ambition |
| LLM spend | Cap **~$5/mo** until Phase 2 | Loop mostly pure Python |

**Date the window** when Phase 1 paper starts: write `EFFICACY_TEST_BTC_YYYY-MM-DD.md` before first counted trade.

---

## 5. Umbrella integration map

| Artifact | Location |
|----------|----------|
| Snapshot | already `snapshot_emit.py` → umbrella sources `btc_bot` |
| Decisions | `data/decisions.ndjson` with real ref_price |
| Outcomes | resolver and/or local settlement writer |
| Findings | weekly job picks up when N>0 real (non-seed) |
| Loop | `umbrella_core.loop` when Phase 2 starts |
| Graveyard | `umbrella` or btc `data/graveyard.jsonl` seeded Phase 2 |

Outer membrane only (own Kalshi account) — **no Robinhood tenancy** issues.

---

## 6. Explicit anti-goals

- Do not re-run weather-Kalshi paper “for learning.”  
- Do not optimize the 97% backtest.  
- Do not add leverage, martingale, or “AI agent trades freely.”  
- Do not build loop before 50 real settlements.  
- Do not treat options-implied as physical probability without documenting RN vs real-world.

---

## 7. Session playbook (how we work this with Grok)

1. **Session start:** STATUS.md + this roadmap + last efficacy numbers.  
2. **One phase slice per session** when possible; always ship a fail-before test.  
3. **Session end:** STATUS + LEDGER + what N is (real only).  
4. **Hand Claude:** step-0 receipts and later holdout net EV — not narrative win rates.

---

## 8. Immediate next step

**Phase 0 status (2026-07-10):** 0.1–0.7 **code complete**; first live capture wrote 15 markets.
**Still open for Phase 0 exit:** accumulate **≥50 settlements** via scheduled capture + `run_phase0_settlements.py`.

No strategy tuning. No loop. No leverage until Phase 2 green.

### Commands
```bash
export PYTHONPATH=".:$HOME/Desktop/umbrella"
python deploy/run_phase0_capture.py --once          # or --loops 30 --interval 120
python deploy/run_phase0_settlements.py
python -m pytest tests/test_phase0_*.py -q
```

---

## 9. Honest odds (frame, not a promise)

| Outcome | Prior (qualitative) |
|---------|---------------------|
| FLOORED after honest N | **Likely** — fee peak at 50¢ is a hard headwind |
| Small positive net EV maker-only niche | **Plausible, unproven** — the open question |
| Twitter-style levered riches | **Not our target**; treat as noise |

Willingness to **kill cleanly** is what makes the experiment worth dedicated hours.

---

*Living doc. Date material edits. Do not rewrite kill criteria after the window starts.*
