"""Phase 1 per-market pricing + signal + umbrella emit (anchor A: spot + realized vol).

`price_and_signal_market` is PURE (no I/O) so the decision path is unit-tested end to end.
The async fetch loop lives in deploy/run_phase1.py and calls this per market.

Scope: KXBTCD strike contracts only. KXBTC15M ("up in 15 min?") are skipped with an explicit
reason — they need the window-open reference price the capture data doesn't carry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from measurement.book import BookSnap
from strategy.fair_value import digital_yes_prob, parse_strike, realized_vol_annual, tte_years
from strategy.signal import evaluate_entry

STRATEGY_EXPERIMENT_ID = "btc-phase1-strategy"

# Near expiry the digital collapses to a step function (sigma*sqrt(T) -> 0), so fair value
# saturates and RV-based pricing is meaningless. Only price contracts with real time left.
# KXBTCD settle on a named date; same-day contracts are hours out (skipped), multi-day ones
# (e.g. "Bitcoin price on Jul 17" seen on Jul 13) clear this floor.
MIN_TTE_DAYS = 0.5
_MIN_TTE_YEARS = MIN_TTE_DAYS / 365.0


def _parse_close_ts(close_time: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(close_time.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def price_and_signal_market(
    market: dict[str, Any],
    book: BookSnap,
    *,
    spot_usd: float,
    vol_annual: float,
    now_ts: float,
    min_edge_usd: float = 0.0,
) -> dict[str, Any]:
    """Return a decision dict for one market: {action, reason, ...}.

    action ∈ {entry, reject, skip}. `skip` = not priceable here (no strike / expired / bad vol);
    it is NOT a strategy rejection, so it must not count as a strategy settlement.
    """
    ticker = str(market.get("ticker", ""))
    strike = parse_strike(ticker)
    if strike is None:
        return {"action": "skip", "reason": "no_strike (non-KXBTCD)", "ticker": ticker}

    close_ts = _parse_close_ts(str(market.get("close_time", "")))
    if close_ts is None:
        return {"action": "skip", "reason": "no_close_time", "ticker": ticker}
    tte = tte_years(now_ts, close_ts)
    if tte is None:
        return {"action": "skip", "reason": "expired", "ticker": ticker}
    if tte < _MIN_TTE_YEARS:
        return {"action": "skip", "reason": f"too_short_dated (<{MIN_TTE_DAYS}d)", "ticker": ticker}

    if not (vol_annual and vol_annual > 0):
        return {"action": "skip", "reason": "no_vol", "ticker": ticker}

    p_fair = digital_yes_prob(spot_usd, strike, tte, vol_annual)
    if p_fair is None:
        return {"action": "skip", "reason": "no_fair_value", "ticker": ticker}

    decision = evaluate_entry(
        p_fair=p_fair, yes_bid=book.yes_bid, no_bid=book.no_bid, min_edge_usd=min_edge_usd,
    )
    decision.update({"ticker": ticker, "strike": strike, "tte_years": tte, "spot": spot_usd})
    return decision


def build_strategy_decision(
    decision: dict[str, Any],
    *,
    spot_usd: float,
    vol_annual: float,
) -> Optional[dict[str, Any]]:
    """Umbrella decision record for a Phase-1 ENTRY (type:prob). None for skip/reject.

    Rejects are not emitted as strategy positions (no fill); only entries create a scored
    prob decision. Kept separate from Phase-0 via experiment_id + phase.
    """
    if decision.get("action") != "entry":
        return None
    from decision_emit import build_decision_record  # local import; matches Phase-0 pattern

    return build_decision_record(
        kind="entry",
        instrument=str(decision["ticker"]),
        reason=str(decision.get("reason", "phase1 maker entry")),
        mode="paper",
        side="buy",
        qty=1.0,
        ref_price=float(decision["entry_price"]),
        entry_price_source=f"kalshi_{decision['side']}_bid_maker",
        prediction={"type": "prob", "p_up": float(decision["p_fair"]), "horizon_days": 1},
        benchmarks={"BTC_USD": float(spot_usd)},
        lineage={
            "trigger": "phase1_strategy",
            "anchor": "spot_realized_vol",
            "side": decision["side"],
            "role": "maker",
            "strike": decision.get("strike"),
            "vol_annual": round(float(vol_annual), 6),
            "net_ev": round(float(decision.get("net_ev", 0.0)), 6),
            "llm_calls": 0,
            "llm_cost_usd": 0.0,
        },
        experiment_id=STRATEGY_EXPERIMENT_ID,
    )


def _iso_now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def realized_vol_from_spot_series(prices: list[float], *, interval_seconds: float) -> Optional[float]:
    """Thin pass-through so the runner has one import surface for RV."""
    return realized_vol_annual(prices, interval_seconds=interval_seconds)
