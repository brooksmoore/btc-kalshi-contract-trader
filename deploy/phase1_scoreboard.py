#!/usr/bin/env python3
"""Write PHASE1_SCOREBOARD.md from phase1_settlements.jsonl (kill-window read).

Primary unit: independent bets (one per ticker). Raw cycle N is diagnostic only.
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


def build_notes(
    ind: dict,
    raw: dict,
    n_entries: int,
) -> list[str]:
    notes: list[str] = []
    n = ind.get("n") or 0
    mean = ind.get("mean_net") or 0.0
    t = ind.get("t_stat")
    raw_n = raw.get("n") or 0
    if raw_n > 0 and n > 0 and raw_n != n:
        notes.append(
            f"Dedup: raw cycle settlements={raw_n} → independent N={n} "
            f"(inflation ×{raw_n / n:.1f}). Primary kill uses independent only."
        )
    if n_entries > 0:
        notes.append(
            f"Logged raw entries (post-fix)={n_entries}. "
            "Going forward the runner logs at most one open position per ticker."
        )
    penny = ind.get("penny_share_le_05")
    if penny is not None:
        notes.append(
            f"Share of independent entries with entry_price ≤ $0.05: {penny:.1%}."
        )
    if n > 0:
        t_bit = f", t={t}" if t is not None else ""
        if mean <= 0:
            notes.append(
                f"Independent mean net {mean:.6f}/bet ≤ 0 after maker fees{t_bit} — "
                "honest money-result direction for anchor A."
            )
        else:
            notes.append(
                f"Independent mean net {mean:.6f}/bet > 0{t_bit} — edge candidate only "
                "until N≥150 (and t≥2 for Anchor B)."
            )
    by_tte = ind.get("by_tte_bucket") or {}
    below = by_tte.get("<0.5d (below claimed gate)")
    if below and below.get("n", 0) > 0:
        notes.append(
            f"WARNING: {below['n']} independent rows had TTE < 0.5d at entry."
        )
    notes.append(
        "Settlement PnL never uses p_fair; result from Kalshi market.result; "
        "fees from measurement.fees maker schedule."
    )
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_MD)
    ap.add_argument(
        "--raw-only",
        action="store_true",
        help="legacy: score raw cycle rows only (not recommended)",
    )
    # --independent is default; kept as explicit flag for handoff wording
    ap.add_argument(
        "--independent",
        action="store_true",
        default=True,
        help="primary: one bet per ticker (default)",
    )
    args = ap.parse_args()

    entries = load_phase1_entries(POSITIONS, require_post_fix=True)
    settled_ids = settled_decision_ids(SETTLEMENTS)
    entry_ids = {str(e.get("decision_id")) for e in entries if e.get("decision_id")}
    n_open = len(entry_ids - settled_ids)

    rows = _enrich(read_jsonl(SETTLEMENTS))
    rows = [r for r in rows if str(r.get("phase", "1")) == "1"]

    raw_stats = score_settlements(rows, independent=False)
    if args.raw_only:
        stats = raw_stats
        notes = build_notes(raw_stats, raw_stats, n_entries=len(entries))
        md = format_scoreboard_md(
            stats,
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            n_entries_post_fix=len(entries),
            n_settled=stats["n"],
            n_open=n_open,
            notes=notes,
            raw_stats=None,
        )
    else:
        ind_stats = score_settlements(rows, independent=True)
        notes = build_notes(ind_stats, raw_stats, n_entries=len(entries))
        md = format_scoreboard_md(
            ind_stats,
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            n_entries_post_fix=len(entries),
            n_settled=ind_stats["n"],
            n_open=n_open,
            notes=notes,
            raw_stats=raw_stats,
        )

    args.out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nWrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
