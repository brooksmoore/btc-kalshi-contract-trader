"""Phase 1 strategy gate: fair value + net-edge-gated maker-first signal.

Hand-computed digital probabilities and edge-gating. No network, no LLM.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.fair_value import (
    digital_yes_prob,
    parse_strike,
    realized_vol_annual,
    tte_years,
)
from strategy.signal import evaluate_entry


# ── fair value ────────────────────────────────────────────────────────────────

def test_parse_strike_from_kxbtcd_ticker() -> None:
    assert parse_strike("KXBTCD-26JUL1016-T71799.99") == 71799.99
    assert parse_strike("KXBTCD-26JUL1016-T70000") == 70000.0
    # KXBTC15M direction contracts have no strike -> None (runner must skip them)
    assert parse_strike("KXBTC15M-26JUL101600-00") is None


def test_digital_at_the_money_is_near_half() -> None:
    # spot == strike, driftless -> d2 = -0.5*sigma*sqrt(T), slightly below 0.5
    p = digital_yes_prob(spot=70000, strike=70000, tte_yr=1.0 / 365, vol_annual=0.6)
    assert p is not None
    assert 0.45 < p < 0.5  # just under a coin flip (vol drag in d2)


def test_digital_deep_in_the_money_high_prob() -> None:
    # spot far above strike -> YES very likely
    p = digital_yes_prob(spot=80000, strike=70000, tte_yr=1.0 / 365, vol_annual=0.6)
    assert p is not None and p > 0.95


def test_digital_hand_computed() -> None:
    # S=71000, K=70000, T=1/365 yr, sigma=0.60
    S, K, T, sig = 71000.0, 70000.0, 1.0 / 365, 0.60
    d2 = (math.log(S / K) - 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    expected = 0.5 * (1 + math.erf(d2 / math.sqrt(2)))
    got = digital_yes_prob(S, K, T, sig)
    assert got is not None and abs(got - expected) < 1e-6


def test_fair_value_fail_closed_on_bad_inputs() -> None:
    assert digital_yes_prob(0, 70000, 0.01, 0.6) is None
    assert digital_yes_prob(70000, 70000, 0, 0.6) is None
    assert digital_yes_prob(70000, 70000, 0.01, 0) is None


def test_realized_vol_annual_and_tte() -> None:
    # flat series -> ~0 vol; None on too-few points
    assert realized_vol_annual([70000, 70000, 70000, 70000], interval_seconds=120) == 0.0
    assert realized_vol_annual([70000], interval_seconds=120) is None
    # a moving series gives a positive annualized number
    v = realized_vol_annual([70000, 70100, 69950, 70200, 70050], interval_seconds=120)
    assert v is not None and v > 0
    assert tte_years(1000.0, 1000.0) is None  # expired
    assert tte_years(0.0, _one_hour := 3600.0) is not None


# ── signal (net-edge gating) ──────────────────────────────────────────────────

def test_entry_when_fair_far_above_market() -> None:
    # model says YES ~0.80 true, market YES bid only 0.55 -> maker YES buy is +EV
    d = evaluate_entry(p_fair=0.80, yes_bid=0.55, no_bid=0.44)
    assert d["action"] == "entry"
    assert d["side"] == "yes"
    assert d["net_ev"] > 0


def test_reject_when_no_edge_over_cost() -> None:
    # Bids AT fair value on both sides: buying YES at 0.50 when fair is 0.50 is 0 gross minus
    # the maker fee -> negative net EV -> reject. (A bid BELOW fair, e.g. 0.49, is a real 1c
    # edge that maker-first correctly captures — that's the point of maker-first, not a bug.)
    d = evaluate_entry(p_fair=0.50, yes_bid=0.50, no_bid=0.50)
    assert d["action"] == "reject"


def test_reject_fail_closed_on_missing_fair_value() -> None:
    d = evaluate_entry(p_fair=None, yes_bid=0.40, no_bid=0.58)  # type: ignore[arg-type]
    assert d["action"] == "reject"
    assert d["reason"] == "no_fair_value"


def test_min_edge_floor_blocks_marginal_trades() -> None:
    # A trade that is barely +EV at floor=0 must be REJECTED once a positive floor is set.
    base = evaluate_entry(p_fair=0.62, yes_bid=0.58, no_bid=0.41, min_edge_usd=0.0)
    if base["action"] == "entry":
        raised = evaluate_entry(
            p_fair=0.62, yes_bid=0.58, no_bid=0.41, min_edge_usd=base["net_ev"] + 0.01
        )
        assert raised["action"] == "reject"


# ── runner (per-market pricing + signal path) ──────────────────────────────────

def _book(yes_bid=None, yes_ask=None, no_bid=None, no_ask=None):
    from measurement.book import BookSnap
    return BookSnap(ticker="t", yes_bid=yes_bid, yes_ask=yes_ask,
                    no_bid=no_bid, no_ask=no_ask, raw_keys=[])


def test_runner_skips_non_kxbtcd() -> None:
    from strategy.runner import price_and_signal_market
    mkt = {"ticker": "KXBTC15M-26JUL101600-00", "close_time": "2026-07-10T20:00:00Z"}
    d = price_and_signal_market(mkt, _book(yes_bid=0.5, no_bid=0.5),
                                spot_usd=70000, vol_annual=0.6, now_ts=0.0)
    assert d["action"] == "skip" and "no_strike" in d["reason"]


def test_runner_skips_expired() -> None:
    from strategy.runner import price_and_signal_market
    mkt = {"ticker": "KXBTCD-26JUL1016-T70000", "close_time": "2026-07-10T20:00:00Z"}
    # now_ts far after close -> expired skip
    d = price_and_signal_market(mkt, _book(yes_bid=0.5, no_bid=0.5),
                                spot_usd=70000, vol_annual=0.6, now_ts=2e9)
    assert d["action"] == "skip" and d["reason"] == "expired"


def test_runner_prices_and_enters_when_mispriced() -> None:
    import time
    from strategy.runner import build_strategy_decision, price_and_signal_market
    # spot 75000 vs strike 70000, ~1 day out -> YES very likely; market YES bid only 0.55 -> entry
    close = time.time() + 86400
    mkt = {"ticker": "KXBTCD-26JUL1016-T70000",
           "close_time": _iso_from_ts(close)}
    d = price_and_signal_market(mkt, _book(yes_bid=0.55, no_bid=0.44),
                                spot_usd=75000, vol_annual=0.6, now_ts=time.time())
    assert d["action"] == "entry" and d["side"] == "yes"
    rec = build_strategy_decision(d, spot_usd=75000, vol_annual=0.6)
    assert rec is not None
    assert rec["prediction"]["type"] == "prob"
    assert rec["experiment_id"] == "btc-phase1-strategy"


def test_build_strategy_decision_none_for_reject() -> None:
    from strategy.runner import build_strategy_decision
    assert build_strategy_decision({"action": "reject"}, spot_usd=70000, vol_annual=0.6) is None


def _iso_from_ts(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def test_vol_plausibility_guard_blocks_degenerate_estimates() -> None:
    from strategy.fair_value import vol_is_plausible
    assert vol_is_plausible(0.60) is True       # realistic BTC vol
    assert vol_is_plausible(0.0346) is False     # the phantom-edge bug: too low
    assert vol_is_plausible(0.0) is False
    assert vol_is_plausible(None) is False
    assert vol_is_plausible(5.0) is False        # absurdly high
