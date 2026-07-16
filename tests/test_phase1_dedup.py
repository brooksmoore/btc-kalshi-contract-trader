"""Fail-before gates: Phase-1 one-entry-per-open-ticker + independent scoreboard N."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measurement.phase1_dedup import (
    independent_settlements,
    mark_opened,
    open_tickers,
    should_count_new_entry,
)
from measurement.phase1_score import score_settlements


def test_five_cycles_same_ticker_counts_exactly_one_entry() -> None:
    """Same open contract across 5 consecutive cycles → exactly 1 counted entry."""
    open: set[str] = set()
    ticker = "KXBTCD-26JUL1617-T65000"
    counted = 0
    for _ in range(5):
        if should_count_new_entry(ticker, open):
            mark_opened(open, ticker)
            counted += 1
    assert counted == 1
    assert open == {ticker}
    # still open → still blocked
    assert should_count_new_entry(ticker, open) is False


def test_different_strike_logs_new_bet() -> None:
    """A genuinely different strike is a different bet — do not over-suppress."""
    open: set[str] = set()
    a = "KXBTCD-26JUL1617-T65000"
    b = "KXBTCD-26JUL1617-T66000"
    assert should_count_new_entry(a, open)
    mark_opened(open, a)
    assert should_count_new_entry(b, open)
    mark_opened(open, b)
    assert open == {a, b}
    assert should_count_new_entry(a, open) is False
    assert should_count_new_entry(b, open) is False


def test_settled_ticker_can_reenter() -> None:
    """After the only open decision settles, ticker is free for a new bet."""
    positions = [
        {"ticker": "T1", "decision_id": "d1"},
        {"ticker": "T2", "decision_id": "d2"},
    ]
    # only d1 settled → T1 free, T2 still open
    open = open_tickers(positions, settled_decision_ids={"d1"})
    assert "T1" not in open
    assert "T2" in open
    assert should_count_new_entry("T1", open)
    assert not should_count_new_entry("T2", open)


def test_independent_scoreboard_n_equals_unique_tickers() -> None:
    """--independent N equals unique (ticker, entry-event), not raw cycle count."""
    rows = []
    # ticker A re-logged 5 times (cycle inflation)
    for i in range(5):
        rows.append({
            "ticker": "TICK-A",
            "decision_id": f"a{i}",
            "ts": f"2026-07-14T0{i}:00:00Z",
            "net_pnl": -0.10,
            "gross_pnl": -0.10,
            "fees": 0.0,
            "side": "yes",
            "entry_price": 0.10,
        })
    # ticker B once
    rows.append({
        "ticker": "TICK-B",
        "decision_id": "b0",
        "ts": "2026-07-14T12:00:00Z",
        "net_pnl": 0.05,
        "gross_pnl": 0.05,
        "fees": 0.0,
        "side": "no",
        "entry_price": 0.20,
    })
    assert len(rows) == 6
    ind_rows = independent_settlements(rows)
    assert len(ind_rows) == 2
    assert {r["ticker"] for r in ind_rows} == {"TICK-A", "TICK-B"}
    # first entry-event for A is a0
    a = next(r for r in ind_rows if r["ticker"] == "TICK-A")
    assert a["decision_id"] == "a0"

    stats = score_settlements(rows, independent=True)
    assert stats["n"] == 2
    assert stats["unique_tickers"] == 2
    assert stats["raw_n"] == 6
    assert stats["mode"] == "independent"

    raw = score_settlements(rows, independent=False)
    assert raw["n"] == 6
