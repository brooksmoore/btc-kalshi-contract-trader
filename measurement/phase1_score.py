"""Phase-1 kill-window scoring — pure join + verdict (no strategy changes).

Pre-registered kill: EFFICACY_TEST_BTC_2026-07-11.md
  KILL_N = 150 (hard min 100 for any verdict)
  FLOORED if mean net_ev_oos <= 0 at N >= KILL_N
  CONTINUE only if mean > 0 at N >= KILL_N

Contamination guard: only entries with ts >= POST_FIX_CUTOFF (2026-07-13) count.
Settlement truth never uses model p_fair (self_score_guard on record path).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .store import read_jsonl

# Phantom-edge purge completed 2026-07-13 — nothing earlier may enter the kill window.
POST_FIX_CUTOFF = datetime(2026, 7, 13, 0, 0, 0, tzinfo=timezone.utc)
POST_FIX_CUTOFF_ISO = "2026-07-13T00:00:00Z"

KILL_N = 150
MIN_VERDICT_N = 100  # no FLOOR/PASS verdict below this (efficacy doc)

# TTE buckets for the claimed min-TTE=0.5d filter
TTE_BUCKETS = (
    ("<0.5d (below claimed gate)", 0.0, 0.5),
    ("0.5–1d", 0.5, 1.0),
    ("1–3d", 1.0, 3.0),
    (">=3d", 3.0, float("inf")),
    ("unknown_tte", None, None),
)


def parse_ts(ts: str | None) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def is_post_fix(ts: str | None) -> bool:
    """True only if entry timestamp is on/after the 2026-07-13 phantom-edge fix."""
    dt = parse_ts(ts)
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= POST_FIX_CUTOFF


def entry_price_source_for_side(side: str) -> str:
    """External book source labels used by Phase-1 emit (self_score_guard-safe)."""
    s = (side or "yes").lower()
    if s == "no":
        return "kalshi_no_bid_maker"
    return "kalshi_yes_bid_maker"


def load_phase1_entries(
    path: str | Path,
    *,
    require_post_fix: bool = True,
) -> list[dict[str, Any]]:
    """Load phase1_positions.jsonl; optionally drop pre-fix contamination."""
    rows = read_jsonl(path)
    if not require_post_fix:
        return rows
    return [r for r in rows if is_post_fix(r.get("ts"))]


def settled_decision_ids(path: str | Path) -> set[str]:
    return {str(r.get("decision_id")) for r in read_jsonl(path) if r.get("decision_id")}


def tte_days_at_entry(entry_ts: str | None, close_time: str | None) -> Optional[float]:
    """Calendar-day TTE from entry timestamp to market close_time (independent of p_fair)."""
    e = parse_ts(entry_ts)
    c = parse_ts(close_time)
    if e is None or c is None:
        return None
    if e.tzinfo is None:
        e = e.replace(tzinfo=timezone.utc)
    if c.tzinfo is None:
        c = c.replace(tzinfo=timezone.utc)
    return (c - e).total_seconds() / 86400.0


def tte_bucket_label(tte_days: Optional[float]) -> str:
    if tte_days is None:
        return "unknown_tte"
    for label, lo, hi in TTE_BUCKETS:
        if lo is None:
            continue
        if lo <= tte_days < hi:
            return label
    return "unknown_tte"


def kill_verdict(*, n: int, mean_net: float) -> str:
    """Map (N, mean net EV/contract) to the pre-registered kill line.

    Handoff wording:
      FLOOR (mean <= 0) / edge candidate (mean > 0, N<150 keep going) /
      PASS (mean > 0 at N>=150 across >=2 regimes)
    Efficacy doc: no FLOOR claim before N>=100; we still label mean<=0 as FLOOR
    when N is large enough to matter, else INSUFFICIENT with the direction.
    """
    if n <= 0:
        return "INSUFFICIENT (N=0 — no Phase-1 settlements yet)"
    if mean_net <= 0:
        if n >= KILL_N:
            return "FLOOR (mean ≤ 0)"
        if n >= MIN_VERDICT_N:
            return "FLOOR (mean ≤ 0) — early (N≥100 but N<KILL_N=150; same direction)"
        return f"INSUFFICIENT (mean ≤ 0, N={n}<100 — keep settling; not a final floor yet)"
    # mean_net > 0
    if n >= KILL_N:
        return "PASS (mean > 0 at N≥150 — regimes column separate; confirm ≥2 regimes before CONTINUE)"
    return "edge candidate (mean > 0, N<150 keep going)"


def score_settlements(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One-page numbers from Phase-1 settlement rows (already fee-honest)."""
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "mean_net": 0.0,
            "win_pct": 0.0,
            "total_net": 0.0,
            "total_gross": 0.0,
            "total_fees": 0.0,
            "wins": 0,
            "losses": 0,
            "verdict": kill_verdict(n=0, mean_net=0.0),
            "by_side": {},
            "by_tte_bucket": {},
            "unique_tickers": 0,
            "entry_price_p50": None,
            "entry_price_mean": None,
            "penny_share_le_05": None,
        }

    nets = [float(r.get("net_pnl") or 0.0) for r in rows]
    grosses = [float(r.get("gross_pnl") or 0.0) for r in rows]
    fees = [float(r.get("fees") or 0.0) for r in rows]
    wins = sum(1 for g in grosses if g > 0)
    losses = n - wins
    mean_net = sum(nets) / n
    total_net = sum(nets)

    by_side: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = str(r.get("side") or "?")
        bucket = by_side.setdefault(s, {"n": 0, "net": 0.0, "wins": 0})
        bucket["n"] += 1
        bucket["net"] += float(r.get("net_pnl") or 0.0)
        if float(r.get("gross_pnl") or 0.0) > 0:
            bucket["wins"] += 1
    for s, b in by_side.items():
        b["mean_net"] = round(b["net"] / b["n"], 6) if b["n"] else 0.0
        b["win_pct"] = round(100.0 * b["wins"] / b["n"], 2) if b["n"] else 0.0
        b["net"] = round(b["net"], 6)

    by_tte: dict[str, dict[str, Any]] = {}
    for r in rows:
        label = str(r.get("tte_bucket") or tte_bucket_label(r.get("tte_days")))
        bucket = by_tte.setdefault(label, {"n": 0, "net": 0.0, "wins": 0})
        bucket["n"] += 1
        bucket["net"] += float(r.get("net_pnl") or 0.0)
        if float(r.get("gross_pnl") or 0.0) > 0:
            bucket["wins"] += 1
    for label, b in by_tte.items():
        b["mean_net"] = round(b["net"] / b["n"], 6) if b["n"] else 0.0
        b["win_pct"] = round(100.0 * b["wins"] / b["n"], 2) if b["n"] else 0.0
        b["net"] = round(b["net"], 6)

    prices = [float(r["entry_price"]) for r in rows if r.get("entry_price") is not None]
    prices_sorted = sorted(prices)
    p50 = prices_sorted[len(prices_sorted) // 2] if prices_sorted else None
    mean_ep = sum(prices) / len(prices) if prices else None
    penny = (
        sum(1 for p in prices if p <= 0.05) / len(prices) if prices else None
    )

    tickers = {str(r.get("ticker")) for r in rows if r.get("ticker")}

    return {
        "n": n,
        "mean_net": round(mean_net, 6),
        "win_pct": round(100.0 * wins / n, 2),
        "total_net": round(total_net, 6),
        "total_gross": round(sum(grosses), 6),
        "total_fees": round(sum(fees), 6),
        "wins": wins,
        "losses": losses,
        "verdict": kill_verdict(n=n, mean_net=mean_net),
        "by_side": by_side,
        "by_tte_bucket": by_tte,
        "unique_tickers": len(tickers),
        "entry_price_p50": round(p50, 4) if p50 is not None else None,
        "entry_price_mean": round(mean_ep, 4) if mean_ep is not None else None,
        "penny_share_le_05": round(penny, 4) if penny is not None else None,
    }


def format_scoreboard_md(
    stats: dict[str, Any],
    *,
    generated_at: str,
    n_entries_post_fix: int,
    n_settled: int,
    n_open: int,
    notes: list[str] | None = None,
) -> str:
    """Render PHASE1_SCOREBOARD.md body."""
    lines = [
        "# Phase-1 kill-window scoreboard",
        "",
        f"**Generated:** {generated_at}",
        f"**Kill reference:** `EFFICACY_TEST_BTC_2026-07-11.md` (KILL_N={KILL_N}, FLOOR if mean net ≤ 0)",
        f"**Contamination cutoff:** {POST_FIX_CUTOFF_ISO} (post phantom-edge fix only)",
        "",
        "## Verdict",
        "",
        f"**{stats['verdict']}**",
        "",
        "## Headline numbers (fee-honest, maker role)",
        "",
        "| metric | value |",
        "|--------|------:|",
        f"| N settled (post-fix) | {stats['n']} |",
        f"| mean net EV / contract | {stats['mean_net']:.6f} |",
        f"| win % (gross > 0) | {stats['win_pct']:.2f}% |",
        f"| total net P&L | {stats['total_net']:.6f} |",
        f"| total gross P&L | {stats['total_gross']:.6f} |",
        f"| total fees | {stats['total_fees']:.6f} |",
        f"| wins / losses | {stats['wins']} / {stats['losses']} |",
        f"| unique tickers settled | {stats['unique_tickers']} |",
        f"| entry_price median | {stats['entry_price_p50']} |",
        f"| entry_price mean | {stats['entry_price_mean']} |",
        f"| share entry ≤ $0.05 | {stats['penny_share_le_05']} |",
        "",
        "## Pipeline",
        "",
        f"- Post-fix Phase-1 entries logged: **{n_entries_post_fix}**",
        f"- Settled: **{n_settled}**",
        f"- Still open (no market result yet): **{n_open}**",
        "",
        "## By side",
        "",
        "| side | N | mean net | win% | total net |",
        "|------|--:|---------:|-----:|----------:|",
    ]
    for side, b in sorted((stats.get("by_side") or {}).items()):
        lines.append(
            f"| {side} | {b['n']} | {b['mean_net']:.6f} | {b['win_pct']:.2f}% | {b['net']:.6f} |"
        )
    if not stats.get("by_side"):
        lines.append("| — | 0 | — | — | — |")

    lines += [
        "",
        "## By TTE at entry (claimed filter: min 0.5 day)",
        "",
        "| TTE bucket | N | mean net | win% | total net |",
        "|------------|--:|---------:|-----:|----------:|",
    ]
    order = [t[0] for t in TTE_BUCKETS]
    by_tte = stats.get("by_tte_bucket") or {}
    for label in order:
        if label not in by_tte:
            continue
        b = by_tte[label]
        lines.append(
            f"| {label} | {b['n']} | {b['mean_net']:.6f} | {b['win_pct']:.2f}% | {b['net']:.6f} |"
        )
    for label, b in sorted(by_tte.items()):
        if label in order:
            continue
        lines.append(
            f"| {label} | {b['n']} | {b['mean_net']:.6f} | {b['win_pct']:.2f}% | {b['net']:.6f} |"
        )
    if not by_tte:
        lines.append("| — | 0 | — | — | — |")

    lines += [
        "",
        "## Penny-entry / residual phantom read",
        "",
    ]
    if notes:
        for n in notes:
            lines.append(f"- {n}")
    else:
        lines.append("- _(no notes)_")

    lines += [
        "",
        "---",
        "_Measurement only. No live orders. Settlement truth from market result + independent",
        "spot when available — never model p_fair. Fee model: measurement.fees (maker)._",
        "",
    ]
    return "\n".join(lines)
