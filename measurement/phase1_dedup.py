"""Phase-1 independent-bet discipline — one counted entry per open ticker.

Bug (2026-07-16): the paper loop re-logged the same KXBTCD market every ~120s,
inflating N ~73× (2,425 settlements / 33 tickers). Independent N is the unit of
scoring for Anchor A (retrospectively) and Anchor B (going forward).

Rules:
  - While a ticker has any unsettled counted position, do NOT log another entry.
  - After all positions on that ticker settle, a new genuine signal may open a new bet.
  - Scoreboard `--independent` keeps first settlement per ticker (one entry-event).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

from .store import read_jsonl


def open_tickers(
    positions: list[dict[str, Any]],
    settled_decision_ids: set[str],
) -> set[str]:
    """Tickers with at least one counted position that has not yet settled."""
    open_set: set[str] = set()
    for row in positions:
        did = str(row.get("decision_id") or "")
        ticker = str(row.get("ticker") or "")
        if not ticker or not did:
            continue
        if did not in settled_decision_ids:
            open_set.add(ticker)
    return open_set


def open_tickers_from_paths(
    positions_path: str | Path,
    settlements_path: str | Path,
) -> set[str]:
    settled = {
        str(r.get("decision_id"))
        for r in read_jsonl(settlements_path)
        if r.get("decision_id")
    }
    return open_tickers(read_jsonl(positions_path), settled)


def should_count_new_entry(ticker: str, open: set[str]) -> bool:
    """True only if this ticker has no open (unsettled) counted position."""
    t = str(ticker or "")
    if not t:
        return False
    return t not in open


def mark_opened(open: set[str], ticker: str) -> None:
    """Record that ticker now has an open counted position (in-memory)."""
    t = str(ticker or "")
    if t:
        open.add(t)


def independent_settlements(
    rows: list[dict[str, Any]],
    *,
    keep: str = "first",
) -> list[dict[str, Any]]:
    """One settlement row per ticker (one entry-event).

    `keep`:
      - first: earliest entry among rows for that ticker (by ts, then decision_id)
      - last: latest entry (for sensitivity; default scoring uses first)
    Historical cycle re-logs of the same market collapse to a single independent bet.
    """
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        t = str(r.get("ticker") or "")
        if not t:
            continue
        by_ticker.setdefault(t, []).append(r)

    def sort_key(r: dict[str, Any]) -> tuple:
        return (str(r.get("ts") or ""), str(r.get("decision_id") or ""))

    out: list[dict[str, Any]] = []
    for t in sorted(by_ticker.keys()):
        group = sorted(by_ticker[t], key=sort_key)
        out.append(group[-1] if keep == "last" else group[0])
    return out


def t_statistic(values: list[float]) -> Optional[float]:
    """Two-sided t on mean vs 0. None if N < 2 or zero variance."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    if var <= 0:
        return None
    se = math.sqrt(var / n)
    if se <= 0:
        return None
    return mean / se
