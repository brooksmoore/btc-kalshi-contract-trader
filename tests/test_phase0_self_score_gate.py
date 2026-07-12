"""Phase 0 gate: forbid model-own-price scoring (97% artifact path)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measurement.self_score_guard import (
    assert_entry_price_is_external,
    is_forbidden_self_score_path,
)
from measurement.settlement import record_settlement


def test_forbidden_markers_detected() -> None:
    assert is_forbidden_self_score_path(entry_price_source="model_own_price")
    assert is_forbidden_self_score_path(
        meta={"note": "used mp - threshold as entry"}
    )
    assert not is_forbidden_self_score_path(entry_price_source="kalshi_yes_ask")


def test_assert_rejects_self_score() -> None:
    with pytest.raises(ValueError, match="forbidden self-score"):
        assert_entry_price_is_external(
            entry_price=0.75,
            entry_price_source="model_own_price",
        )


def test_assert_accepts_kalshi_ask_matching_book() -> None:
    assert_entry_price_is_external(
        entry_price=0.52,
        entry_price_source="kalshi_yes_ask",
        kalshi_ask=0.52,
        kalshi_bid=0.48,
    )


def test_settlement_refuses_self_score(tmp_path: Path) -> None:
    path = tmp_path / "settlements.jsonl"
    with pytest.raises(ValueError, match="forbidden|external"):
        record_settlement(
            path,
            ticker="KXBTC-TEST",
            decision_id="x",
            entry_price=0.75,
            entry_price_source="hardcoded_0.75",
            result="yes",
        )
    assert not path.exists() or path.read_text() == ""


def test_settlement_accepts_external_book(tmp_path: Path) -> None:
    path = tmp_path / "settlements.jsonl"
    row = record_settlement(
        path,
        ticker="KXBTC-TEST",
        decision_id="d1",
        entry_price=0.50,
        entry_price_source="kalshi_yes_ask",
        result="yes",
        kalshi_ask=0.50,
        kalshi_bid=0.48,
        spot_at_entry=64000.0,
    )
    assert row["net_pnl"] < row["gross_pnl"]  # fees deducted
    assert path.exists()
