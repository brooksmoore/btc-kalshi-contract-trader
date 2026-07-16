#!/usr/bin/env python3
"""Write PHASE1_SCOREBOARD.md from phase1_settlements.jsonl (kill-window read).

No network. No strategy. No live path.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measurement.phase1_score import (
    format_scoreboard_md,
    load_phase1_entries,
    score_settlements,
    settled_decision_ids,
)
from measurement.store import read_jsonl

POSITIONS = ROOT / "data" / "phase1_positions.jsonl"
SETTLEMENTS = ROOT / "data" / "phase1_settlements.jsonl"
OUT_MD = ROOT / "PHASE1_SCOREBOARD.md"


def _enrich(rows: list[dict]) -> list[dict]:
    """Promote extra.tte_* onto the row for bucketing."""
    out = []
    for r in rows:
        rr = dict(r)
        extra = r.get("extra") or {}
        if rr.get("tte_days") is None and extra.get("tte_days") is not None:
            rr["tte_days"] = extra.get("tte_days")
        if rr.get("tte_bucket") is None and extra.get("tte_bucket") is not None:
            rr["tte_bucket"] = extra.get("tte_bucket")
        out.append(rr)
    return out


def build_notes(stats: dict, n_entries: int) -> list[str]:
    notes: list[str] = []
    n = stats.get("n") or 0
    mean = stats.get("mean_net") or 0.0
    penny = stats.get("penny_share_le_05")
    uniq = stats.get("unique_tickers") or 0
    if n_entries > 0 and uniq > 0:
        notes.append(
            f"Logged entries (post-fix)={n_entries} across ~{uniq} unique tickers in the "
            f"settled set — re-entry of the same market each cycle inflates N vs independent bets."
        )
    if penny is not None:
        notes.append(
            f"Share of settled entries with entry_price ≤ $0.05: {penny:.1%}. "
            "High share + cheap entry is the residual 'pick up pennies' signature even after the "
            "≥5pp edge gate (cheap side of a large model/market disagreement)."
        )
    if n > 0:
        if mean <= 0:
            notes.append(
                f"Settled mean net {mean:.6f}/contract ≤ 0 after maker fees — "
                "this is the honest money-result direction for anchor A so far."
            )
        else:
            notes.append(
                f"Settled mean net {mean:.6f}/contract > 0 after maker fees — "
                "edge candidate only; no PASS until N≥150 (and ≥2 regimes)."
            )
    by_tte = stats.get("by_tte_bucket") or {}
    below = by_tte.get("<0.5d (below claimed gate)")
    if below and below.get("n", 0) > 0:
        notes.append(
            f"WARNING: {below['n']} settled rows had TTE < 0.5d at entry — claimed MIN_TTE_DAYS "
            "gate may not be binding on all logged entries (or close_time parse differs)."
        )
    elif n > 0 and not any(k.startswith("<0.5") for k in by_tte):
        notes.append(
            "No settled rows in the <0.5d TTE bucket — claimed min-TTE filter looks respected "
            "on the settled sample."
        )
    notes.append(
        "Settlement PnL never uses p_fair; result comes from Kalshi market.result; "
        "fees from measurement.fees maker schedule."
    )
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_MD)
    args = ap.parse_args()

    entries = load_phase1_entries(POSITIONS, require_post_fix=True)
    settled_ids = settled_decision_ids(SETTLEMENTS)
    entry_ids = {str(e.get("decision_id")) for e in entries if e.get("decision_id")}
    n_open = len(entry_ids - settled_ids)

    rows = _enrich(read_jsonl(SETTLEMENTS))
    # Only score phase=1 / post-fix (settlements should already be clean)
    rows = [r for r in rows if str(r.get("phase", "1")) == "1"]
    stats = score_settlements(rows)
    notes = build_notes(stats, n_entries=len(entries))
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    md = format_scoreboard_md(
        stats,
        generated_at=generated,
        n_entries_post_fix=len(entries),
        n_settled=stats["n"],
        n_open=n_open,
        notes=notes,
    )
    args.out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nWrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
