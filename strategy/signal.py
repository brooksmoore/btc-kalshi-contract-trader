"""Phase 1 signal — maker-first, net-of-cost-gated entry decision.

The one boring rule: trade a contract ONLY when the model's fair value diverges from the market
enough that the net-of-fee EV of a MAKER (resting-limit) fill clears a floor. No edge over cost
-> reject. Reuses measurement.fees.net_ev_per_contract (the same cost core Phase 0 validated) —
this module adds NO new fee/EV math.

maker-first: we assume a resting limit at the current best bid on our side (YES buy rests at
yes_bid; NO buy rests at no_bid). This is the pessimistic, honest fill assumption — never
taker-at-the-ask by default (that's where Kalshi's fee moat kills thin brackets).
"""

from __future__ import annotations

from typing import Any, Optional

from measurement.fees import net_ev_per_contract
from strategy.fair_value import is_saturated

# Minimum net EV per contract (USD) required to enter. 0.0 = "any positive net edge"; a small
# positive floor avoids trading marginal noise. Pre-registered knob (kept modest).
DEFAULT_MIN_EDGE_USD = 0.0

# Minimum probability-space disagreement with the market required to enter. Without this, the
# strategy "picks up pennies" — buying a near-certain side at $0.99 for the maker rebate when the
# model and market actually AGREE (both ~1%). That is not edge; it is the clamp artifact that
# produced 46k phantom entries (2026-07-13). Require the model to genuinely disagree by this much.
DEFAULT_MIN_PROB_EDGE = 0.05


def evaluate_entry(
    *,
    p_fair: float,
    yes_bid: Optional[float],
    no_bid: Optional[float],
    min_edge_usd: float = DEFAULT_MIN_EDGE_USD,
    min_prob_edge: float = DEFAULT_MIN_PROB_EDGE,
    maker_mult: float | None = None,
) -> dict[str, Any]:
    """Return a decision dict. action in {entry, reject}.

    Gates, in order (fail-closed — reject on absent/unreliable data):
      1. p_fair present and in [0,1].
      2. p_fair NOT saturated (a clamped fair value is not a real view).
      3. |p_fair - market_yes_prob| >= min_prob_edge (genuine disagreement, not fee-picking).
      4. best maker net EV > min_edge_usd.
    """
    if p_fair is None or not (0.0 <= p_fair <= 1.0):
        return {"action": "reject", "reason": "no_fair_value", "p_fair": p_fair}
    if is_saturated(p_fair):
        return {"action": "reject", "reason": "fair_value_saturated (clamp, no real view)", "p_fair": p_fair}
    kw = {} if maker_mult is None else {"maker_mult": maker_mult}
    candidates: list[dict[str, Any]] = []

    # Probability-space edge PER SIDE, from the price we'd actually pay — never depends on
    # yes_mid being present (deep-OTM books often lack a yes_ask). A maker buy at price P on a
    # side implies the market prices that side at ~P; the model must disagree by min_prob_edge.
    #   YES buy at yes_bid  → market P(YES) ≈ yes_bid        → edge = |p_fair - yes_bid|
    #   NO  buy at no_bid   → market P(YES) ≈ 1 - no_bid     → edge = |p_fair - (1 - no_bid)|
    if yes_bid is not None and 0.0 < yes_bid < 1.0:
        if abs(p_fair - yes_bid) >= min_prob_edge:
            candidates.append({
                "side": "yes", "entry_price": yes_bid,
                "net_ev": net_ev_per_contract(win_prob=p_fair, entry_price=yes_bid,
                                              side="yes", role="maker", **kw),
            })

    if no_bid is not None and 0.0 < no_bid < 1.0:
        if abs(p_fair - (1.0 - no_bid)) >= min_prob_edge:
            candidates.append({
                "side": "no", "entry_price": no_bid,
                "net_ev": net_ev_per_contract(win_prob=p_fair, entry_price=no_bid,
                                              side="no", role="maker", **kw),
            })

    if not candidates:
        return {"action": "reject",
                "reason": f"no side with prob_edge >= {min_prob_edge} (model≈market)",
                "p_fair": p_fair}

    best = max(candidates, key=lambda c: c["net_ev"])
    if best["net_ev"] > min_edge_usd:
        return {
            "action": "entry",
            "side": best["side"],
            "role": "maker",
            "entry_price": best["entry_price"],
            "net_ev": best["net_ev"],
            "p_fair": p_fair,
            "reason": f"maker {best['side']} net_ev={best['net_ev']:.4f} > floor {min_edge_usd}",
        }
    return {
        "action": "reject",
        "reason": f"best net_ev {best['net_ev']:.4f} <= floor {min_edge_usd}",
        "p_fair": p_fair,
        "best_net_ev": best["net_ev"],
    }
