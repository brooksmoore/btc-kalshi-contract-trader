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

# Minimum net EV per contract (USD) required to enter. 0.0 = "any positive net edge"; a small
# positive floor avoids trading marginal noise. Pre-registered knob (kept modest).
DEFAULT_MIN_EDGE_USD = 0.0


def evaluate_entry(
    *,
    p_fair: float,
    yes_bid: Optional[float],
    no_bid: Optional[float],
    min_edge_usd: float = DEFAULT_MIN_EDGE_USD,
    maker_mult: float | None = None,
) -> dict[str, Any]:
    """Return a decision dict. action in {entry, reject}.

    Considers a maker YES buy (rest at yes_bid) and a maker NO buy (rest at no_bid); picks the
    side with the higher net EV if it clears `min_edge_usd`, else rejects. Fail-closed: missing
    prices or a non-finite p_fair -> reject (never trade on absent data).
    """
    if p_fair is None or not (0.0 <= p_fair <= 1.0):
        return {"action": "reject", "reason": "no_fair_value", "p_fair": p_fair}

    kw = {} if maker_mult is None else {"maker_mult": maker_mult}
    candidates: list[dict[str, Any]] = []

    if yes_bid is not None and 0.0 < yes_bid < 1.0:
        ev_yes = net_ev_per_contract(
            win_prob=p_fair, entry_price=yes_bid, side="yes", role="maker", **kw
        )
        candidates.append({"side": "yes", "entry_price": yes_bid, "net_ev": ev_yes})

    if no_bid is not None and 0.0 < no_bid < 1.0:
        # NO buy wins when YES fails; net_ev_per_contract handles the side flip internally.
        ev_no = net_ev_per_contract(
            win_prob=p_fair, entry_price=no_bid, side="no", role="maker", **kw
        )
        candidates.append({"side": "no", "entry_price": no_bid, "net_ev": ev_no})

    if not candidates:
        return {"action": "reject", "reason": "no_tradeable_bid", "p_fair": p_fair}

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
