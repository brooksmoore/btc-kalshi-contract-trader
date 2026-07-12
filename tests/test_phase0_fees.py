"""Phase 0: fee model hand-computed gates."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measurement.fees import (
    maker_fee_per_contract,
    net_ev_per_contract,
    taker_fee_per_contract,
)


def test_taker_fee_at_50c_hand_computed() -> None:
    # 0.07 * 0.5 * 0.5 = 0.0175
    assert taker_fee_per_contract(0.5) == 0.0175
    assert taker_fee_per_contract(50) == 0.0175  # cents form


def test_taker_fee_near_extreme_cheaper() -> None:
    mid = taker_fee_per_contract(0.5)
    extreme = taker_fee_per_contract(0.9)
    assert extreme < mid
    assert abs(extreme - round(0.07 * 0.9 * 0.1, 4)) < 1e-9


def test_maker_cheaper_than_taker() -> None:
    assert maker_fee_per_contract(0.5) < taker_fee_per_contract(0.5)
    assert maker_fee_per_contract(0.5) == round(0.0175 * 0.5 * 0.5, 4)


def test_net_ev_zero_edge_negative_after_taker() -> None:
    # Fair coin, buy YES at 0.50 → gross EV 0, fee 0.0175 → net negative
    nev = net_ev_per_contract(win_prob=0.5, entry_price=0.5, side="yes", role="taker")
    assert nev < 0
    assert abs(nev - (-0.0175)) < 1e-6
