"""Fail-before gates for Anchor B Deribit → risk-neutral digital pricing."""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measurement.anchor_b_pricing import (
    DISAGREE_FLAG,
    DeribitChain,
    bs_call_price,
    digital_n_d2,
    interpolate_iv_term,
    price_digital_from_chain,
    price_kalshi_kxbtcd,
    synthetic_flat_vol_chain,
    tte_years,
)


def test_deep_itm_otm_atm_digital() -> None:
    spot, vol, t = 70000.0, 0.50, 7 / 365.0
    p_atm = digital_n_d2(spot, spot, t, vol, above=True)
    p_itm = digital_n_d2(spot, spot * 0.7, t, vol, above=True)
    p_otm = digital_n_d2(spot, spot * 1.4, t, vol, above=True)
    assert p_atm is not None and 0.45 < p_atm < 0.55
    assert p_itm is not None and p_itm > 0.95
    assert p_otm is not None and p_otm < 0.05


def test_n_d2_and_bl_agree_on_flat_vol_chain() -> None:
    now = time.time()
    exp = now + 7 * 86400
    spot, vol = 65000.0, 0.40
    strikes = [spot + d for d in range(-5000, 5001, 250)]
    chain = synthetic_flat_vol_chain(
        spot=spot, vol=vol, expiry_ts=exp, strikes=strikes, now_ts=now,
    )
    q = price_digital_from_chain(chain, strike=spot, expiry_ts=exp, now_ts=now, above=True)
    assert q.ok
    assert q.p_n_d2 is not None and q.p_bl is not None
    assert abs(q.p_n_d2 - q.p_bl) < 0.05  # well inside DISAGREE_FLAG
    assert q.disagree is not None and q.disagree < DISAGREE_FLAG
    assert not q.disagree_flag
    # ATM ~ 0.5 under r=0 (slightly under from -0.5 sig^2 T in d2)
    assert 0.40 < q.p_yes < 0.55


def test_term_structure_interpolation_between_anchors() -> None:
    # T halfway → IV between the two anchors (total-var interp)
    t0, t1 = 7 / 365.0, 30 / 365.0
    iv0, iv1 = 0.30, 0.50
    t_mid = (t0 + t1) / 2
    iv_mid = interpolate_iv_term(t_mid, t0, iv0, t1, iv1)
    assert iv_mid is not None
    assert min(iv0, iv1) <= iv_mid <= max(iv0, iv1)
    # outside span → None (no extrapolation blowup)
    assert interpolate_iv_term(t1 * 2, t0, iv0, t1, iv1) is None
    assert interpolate_iv_term(t0 / 2, t0, iv0, t1, iv1) is None


def test_term_interp_used_in_chain_pricing() -> None:
    now = time.time()
    e0 = now + 7 * 86400
    e1 = now + 30 * 86400
    spot = 65000.0
    strikes = [spot + d for d in range(-4000, 4001, 500)]
    # two flat-vol chains at different vols, merge
    c0 = synthetic_flat_vol_chain(spot=spot, vol=0.30, expiry_ts=e0, strikes=strikes, now_ts=now)
    c1 = synthetic_flat_vol_chain(spot=spot, vol=0.50, expiry_ts=e1, strikes=strikes, now_ts=now)
    merged = DeribitChain(
        index_usd=spot,
        fetched_ts=now,
        options=list(c0.options) + list(c1.options),
        source="synthetic",
    )
    e_mid = now + 14 * 86400
    q = price_digital_from_chain(merged, strike=spot, expiry_ts=e_mid, now_ts=now)
    assert q.ok and q.iv_used is not None
    assert 0.30 <= q.iv_used <= 0.50


def test_fail_closed_on_empty_or_stale_chain() -> None:
    now = time.time()
    empty = DeribitChain(index_usd=0, fetched_ts=now, options=[], error="no data")
    q = price_digital_from_chain(empty, strike=65000, expiry_ts=now + 86400, now_ts=now)
    assert not q.ok and q.p_yes is None

    stale = synthetic_flat_vol_chain(
        spot=65000, vol=0.4, expiry_ts=now + 86400,
        strikes=[60000, 65000, 70000], now_ts=now - 10_000,
    )
    # override fetched_ts to be old
    stale = DeribitChain(
        index_usd=stale.index_usd,
        fetched_ts=now - 10_000,
        options=stale.options,
    )
    q2 = price_digital_from_chain(stale, strike=65000, expiry_ts=now + 86400, now_ts=now)
    assert not q2.ok and q2.p_yes is None
    assert "stale" in (q2.error or "")


def test_price_kalshi_ticker_parses_strike() -> None:
    now = time.time()
    exp_iso = datetime_utc_iso(now + 2 * 86400)
    exp_ts = now + 2 * 86400
    chain = synthetic_flat_vol_chain(
        spot=64000, vol=0.35, expiry_ts=exp_ts,
        strikes=[60000, 62000, 64000, 66000, 68000], now_ts=now,
    )
    q = price_kalshi_kxbtcd(
        chain,
        ticker="KXBTCD-26JUL1817-T63999.99",
        close_time=exp_iso,
        now_ts=now,
    )
    assert q.ok
    assert abs(q.strike - 63999.99) < 0.01
    assert q.p_yes is not None


def datetime_utc_iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_bs_call_positive_and_decreases_in_strike() -> None:
    t = 14 / 365.0
    c1 = bs_call_price(65000, 64000, t, 0.4)
    c2 = bs_call_price(65000, 66000, t, 0.4)
    assert c1 is not None and c2 is not None
    assert c1 > c2 > 0
