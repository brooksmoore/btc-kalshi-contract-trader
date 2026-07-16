"""Fail-before gates for Phase-1 kill-window scoreboard.

Proves: fee-honest loss settlement, FLOOR vs edge-candidate verdicts, pre-fix exclusion.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measurement.fees import maker_fee_per_contract
from measurement.phase1_score import (
    POST_FIX_CUTOFF_ISO,
    is_post_fix,
    kill_verdict,
    load_phase1_entries,
    score_settlements,
)
from measurement.settlement import realized_pnl_side, record_settlement


def test_loss_settlement_applies_fees_and_direction(tmp_path: Path) -> None:
    """Synthetic YES entry that settles NO → net = -(entry_price + fees), not 0."""
    entry = 0.40
    role = "maker"
    fee = maker_fee_per_contract(entry)
    pnl = realized_pnl_side(
        entry_price=entry, result="no", side="yes", role=role, contracts=1
    )
    # Loss of stake + fee
    assert pnl["gross_pnl"] == pytest.approx(-entry)
    assert pnl["fees"] == pytest.approx(fee)
    assert pnl["net_pnl"] == pytest.approx(-(entry + fee))
    assert pnl["net_pnl"] != 0.0

    path = tmp_path / "phase1_settlements.jsonl"
    row = record_settlement(
        path,
        ticker="KXBTCD-TEST-T70000",
        decision_id="btc:test:loss:1",
        entry_price=entry,
        entry_price_source="kalshi_yes_bid_maker",
        result="no",
        side="yes",
        role="maker",
        phase="1",
    )
    assert row["net_pnl"] == pytest.approx(-(entry + fee))
    assert row["phase"] == "1"


def test_kill_verdict_floor_on_nonpositive_mean() -> None:
    """Scoreboard kill line must read FLOOR when mean net ≤ 0 at large N."""
    rows = [
        {"net_pnl": -0.01, "gross_pnl": -0.01, "fees": 0.0, "side": "yes", "ticker": f"T{i}"}
        for i in range(150)
    ]
    stats = score_settlements(rows)
    assert stats["mean_net"] <= 0
    assert stats["n"] == 150
    assert "FLOOR" in stats["verdict"]
    assert kill_verdict(n=150, mean_net=-0.001).startswith("FLOOR")


def test_kill_verdict_edge_candidate_on_positive_mean_small_n() -> None:
    rows = [
        {"net_pnl": 0.02, "gross_pnl": 0.02, "fees": 0.0, "side": "yes", "ticker": f"T{i}"}
        for i in range(40)
    ]
    stats = score_settlements(rows)
    assert stats["mean_net"] > 0
    assert "edge candidate" in stats["verdict"]
    assert "keep going" in stats["verdict"]


def test_pre_fix_entries_excluded_from_scored_set(tmp_path: Path) -> None:
    """A pre-07-13 entry must not appear in the load used for the kill window."""
    path = tmp_path / "phase1_positions.jsonl"
    path.write_text(
        "\n".join(
            [
                # pre-fix contamination
                '{"ts":"2026-07-12T12:00:00Z","ticker":"OLD","side":"yes","entry_price":0.5,'
                '"p_fair":0.6,"net_ev":0.01,"decision_id":"btc:old:1"}',
                # post-fix clean
                '{"ts":"2026-07-14T12:00:00Z","ticker":"NEW","side":"yes","entry_price":0.5,'
                '"p_fair":0.6,"net_ev":0.01,"decision_id":"btc:new:1"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    loaded = load_phase1_entries(path, require_post_fix=True)
    assert len(loaded) == 1
    assert loaded[0]["decision_id"] == "btc:new:1"
    assert is_post_fix("2026-07-12T23:59:59Z") is False
    assert is_post_fix(POST_FIX_CUTOFF_ISO) is True
    assert is_post_fix("2026-07-14T00:00:00Z") is True
