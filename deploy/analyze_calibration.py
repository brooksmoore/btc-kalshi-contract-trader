"""
Calibration analysis for KXBTC15M strategy.

Reads data/history.json (or --input file) and answers:

  1. MODEL CALIBRATION   — when model says P%, does YES resolve P%?
  2. MARKET EFFICIENCY   — does the market price already capture all the signal?
  3. EDGE SLICES         — are there time-of-day / day-of-week / vol-regime
                           conditions where the market misprice meaningfully?
  4. SIGNAL VIABILITY    — under what threshold would the strategy have been
                           profitable historically?

Output: printed report + data/calibration_report.json

Usage:
    python3.11 deploy/analyze_calibration.py
    python3.11 deploy/analyze_calibration.py --input data/history_60d.json
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── helpers ───────────────────────────────────────────────────────────────────

def mean(vals):
    return sum(vals) / len(vals) if vals else 0.0


def wilson_ci(successes, n, z=1.96):
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = (z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return max(0, centre - margin), min(1, centre + margin)


def ev(model_prob, market_price):
    """Expected value per dollar risked under model_prob."""
    return model_prob * (1 - market_price) - (1 - model_prob) * market_price


def simulated_pnl(result_yes: bool, side: str, price: float, count: int = 1) -> float:
    if side == "yes":
        return (1.0 - price) * count if result_yes else -price * count
    else:
        return (1.0 - price) * count if not result_yes else -price * count


# ── main analysis ─────────────────────────────────────────────────────────────

def analyze(records: list[dict]) -> dict:
    report = {}
    n_total = len(records)

    # ── 1. Overall YES rate ───────────────────────────────────────────────────
    yes_total = sum(1 for r in records if r["result"] == "yes")
    report["dataset"] = {
        "total_contracts": n_total,
        "yes_count": yes_total,
        "no_count": n_total - yes_total,
        "yes_rate": round(yes_total / n_total, 4) if n_total else 0,
    }

    # ── 2. Model calibration by checkpoint ───────────────────────────────────
    calibration = {}
    for mins in [2, 5, 10, 15]:
        buckets = defaultdict(list)
        for r in records:
            for cp in r["checkpoints"]:
                if cp["mins_before_expiry"] == mins:
                    bucket = round(cp["model_prob"] * 10) / 10
                    buckets[bucket].append(r["result"] == "yes")

        rows = []
        for b in sorted(buckets):
            vals = buckets[b]
            actual = mean(vals)
            lo, hi = wilson_ci(sum(vals), len(vals))
            rows.append({
                "model_prob_bucket": b,
                "actual_yes_rate":   round(actual, 4),
                "ci_low":            round(lo, 4),
                "ci_high":           round(hi, 4),
                "n":                 len(vals),
                "calibration_error": round(abs(actual - b), 4),
            })
        calibration[f"t_minus_{mins}min"] = rows

    report["model_calibration"] = calibration

    # ── 3. Would the market price have been a better predictor? ──────────────
    # We don't have the live market price in history, but we can infer it:
    # the market is known to price close to actual yes_rate in aggregate.
    # Instead, check: does btc_vs_strike_pct alone predict result better
    # than model_prob?
    yes_rate_by_dist = defaultdict(list)
    for r in records:
        for cp in r["checkpoints"]:
            if cp["mins_before_expiry"] == 5:
                dist = cp["btc_vs_strike_pct"]
                bucket = round(dist * 4) / 4  # 0.25% buckets
                yes_rate_by_dist[bucket].append(r["result"] == "yes")

    dist_rows = []
    for b in sorted(yes_rate_by_dist):
        vals = yes_rate_by_dist[b]
        actual = mean(vals)
        lo, hi = wilson_ci(sum(vals), len(vals))
        dist_rows.append({
            "btc_vs_strike_pct": b,
            "actual_yes_rate":   round(actual, 4),
            "ci_low":            round(lo, 4),
            "ci_high":           round(hi, 4),
            "n":                 len(vals),
        })
    report["yes_rate_by_distance_to_strike"] = dist_rows

    # ── 4. Edge slices — time of day ─────────────────────────────────────────
    hourly = defaultdict(list)
    for r in records:
        dt = datetime.fromisoformat(r["close_time"])
        hour = dt.hour
        hourly[hour].append(r["result"] == "yes")

    hour_rows = []
    for h in sorted(hourly):
        vals = hourly[h]
        actual = mean(vals)
        lo, hi = wilson_ci(sum(vals), len(vals))
        hour_rows.append({
            "utc_hour":        h,
            "actual_yes_rate": round(actual, 4),
            "ci_low":          round(lo, 4),
            "ci_high":         round(hi, 4),
            "n":               len(vals),
        })
    report["yes_rate_by_utc_hour"] = hour_rows

    # ── 5. Edge slices — day of week ─────────────────────────────────────────
    daily = defaultdict(list)
    dow_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    for r in records:
        dt = datetime.fromisoformat(r["close_time"])
        daily[dt.weekday()].append(r["result"] == "yes")

    dow_rows = []
    for d in sorted(daily):
        vals = daily[d]
        actual = mean(vals)
        lo, hi = wilson_ci(sum(vals), len(vals))
        dow_rows.append({
            "day":             dow_names[d],
            "actual_yes_rate": round(actual, 4),
            "ci_low":          round(lo, 4),
            "ci_high":         round(hi, 4),
            "n":               len(vals),
        })
    report["yes_rate_by_day_of_week"] = dow_rows

    # ── 6. Edge slices — recent BTC volatility (proxy: |btc_vs_strike| at T-15) ──
    vol_buckets = defaultdict(list)
    for r in records:
        for cp in r["checkpoints"]:
            if cp["mins_before_expiry"] == 15:
                abs_dist = abs(cp["btc_vs_strike_pct"])
                bucket = "far (>1%)" if abs_dist > 1.0 else ("mid (0.25-1%)" if abs_dist > 0.25 else "near (<0.25%)")
                vol_buckets[bucket].append(r["result"] == "yes")

    vol_rows = []
    for b in ["near (<0.25%)", "mid (0.25-1%)", "far (>1%)"]:
        if b not in vol_buckets:
            continue
        vals = vol_buckets[b]
        actual = mean(vals)
        lo, hi = wilson_ci(sum(vals), len(vals))
        vol_rows.append({
            "distance_bucket": b,
            "actual_yes_rate": round(actual, 4),
            "ci_low":          round(lo, 4),
            "ci_high":         round(hi, 4),
            "n":               len(vals),
        })
    report["yes_rate_by_distance_bucket"] = vol_rows

    # ── 7. Strategy viability — simulated PnL at various thresholds ──────────
    # Simulate: for each contract, at T-5min, if model_prob - market_proxy > threshold,
    # buy YES. Market proxy = actual yes rate in the model_prob bucket (from calibration).
    # Since we don't have live market prices, use the bucket's actual_yes_rate as
    # a proxy for what the market was pricing (conservative — real market may differ).
    # Also test: only trade when BTC is already above strike (model_prob > 0.5).

    threshold_results = []
    for threshold in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]:
        trades = []
        for r in records:
            for cp in r["checkpoints"]:
                if cp["mins_before_expiry"] != 5:
                    continue
                mp = cp["model_prob"]
                # Only trade when model sees meaningful edge vs 0.5 baseline
                if mp > 0.5 + threshold:
                    # Bet YES (BTC above strike, model strongly YES)
                    pnl = simulated_pnl(r["result"] == "yes", "yes", mp - threshold)
                    trades.append(pnl)
                elif mp < 0.5 - threshold:
                    # Bet NO (BTC below strike, model strongly NO)
                    pnl = simulated_pnl(r["result"] == "yes", "no", 0.5 - mp)
                    trades.append(pnl)

        if trades:
            wins = sum(1 for t in trades if t > 0)
            total_pnl = sum(trades)
            threshold_results.append({
                "threshold":     threshold,
                "trade_count":   len(trades),
                "win_rate":      round(wins / len(trades), 4),
                "total_pnl":     round(total_pnl, 4),
                "avg_pnl":       round(total_pnl / len(trades), 4),
            })
        else:
            threshold_results.append({
                "threshold": threshold, "trade_count": 0,
                "win_rate": 0, "total_pnl": 0, "avg_pnl": 0,
            })

    report["threshold_viability"] = threshold_results

    # ── 8. Regime-aware strategy: only trade when model is well-calibrated ────
    # From calibration: model is accurate when prob > 0.6 or prob < 0.4.
    # Test: only enter when model_prob > 0.65 or model_prob < 0.35.
    regime_trades = []
    for r in records:
        for cp in r["checkpoints"]:
            if cp["mins_before_expiry"] != 5:
                continue
            mp = cp["model_prob"]
            if mp >= 0.65:
                # Strong YES signal, buy at ask approximated as actual_yes_rate
                pnl = simulated_pnl(r["result"] == "yes", "yes", 0.75)  # assume market ~75¢
                regime_trades.append(("strong_yes", pnl, r["result"]))
            elif mp <= 0.35:
                # Strong NO signal, buy NO at ~25¢
                pnl = simulated_pnl(r["result"] == "yes", "no", 0.25)
                regime_trades.append(("strong_no", pnl, r["result"]))

    if regime_trades:
        wins = sum(1 for _, pnl, _ in regime_trades if pnl > 0)
        total = sum(pnl for _, pnl, _ in regime_trades)
        report["calibrated_regime_strategy"] = {
            "description": "Only trade when model_prob > 0.65 (buy YES) or < 0.35 (buy NO)",
            "trade_count": len(regime_trades),
            "win_rate":    round(wins / len(regime_trades), 4),
            "total_pnl":   round(total, 4),
            "avg_pnl":     round(total / len(regime_trades), 4),
            "note": "Entry prices are approximated — real market prices needed for live validation",
        }

    return report


# ── pretty-print ──────────────────────────────────────────────────────────────

def print_report(report: dict) -> None:
    d = report["dataset"]
    print("\n" + "="*65)
    print("  KXBTC15M CALIBRATION ANALYSIS")
    print("="*65)
    print(f"  Contracts: {d['total_contracts']}  |  YES: {d['yes_count']} ({d['yes_rate']*100:.1f}%)  |  NO: {d['no_count']}")

    print("\n── Model Calibration at T-5min (does model prob = actual rate?) ──")
    print(f"  {'Model%':>8}  {'Actual%':>8}  {'CI':>16}  {'Error':>7}  {'n':>5}")
    for row in report["model_calibration"]["t_minus_5min"]:
        flag = " ◄ TRADES HERE" if 0.1 <= row["model_prob_bucket"] <= 0.4 else ""
        print(f"  {row['model_prob_bucket']*100:>7.0f}%  {row['actual_yes_rate']*100:>7.1f}%  "
              f"  [{row['ci_low']*100:.0f}%–{row['ci_high']*100:.0f}%]  "
              f"{row['calibration_error']*100:>6.1f}pp  {row['n']:>5}{flag}")

    print("\n── YES Rate by Distance to Strike at T-5min ──")
    print(f"  {'Dist%':>8}  {'YES%':>8}  {'CI':>16}  {'n':>5}")
    for row in report["yes_rate_by_distance_to_strike"]:
        print(f"  {row['btc_vs_strike_pct']:>8.2f}%  {row['actual_yes_rate']*100:>7.1f}%  "
              f"  [{row['ci_low']*100:.0f}%–{row['ci_high']*100:.0f}%]  {row['n']:>5}")

    print("\n── YES Rate by UTC Hour (potential time-of-day edge?) ──")
    print(f"  {'Hour':>6}  {'YES%':>8}  {'CI':>16}  {'n':>5}")
    for row in report["yes_rate_by_utc_hour"]:
        flag = " ◄" if row["ci_low"] > 0.55 or row["ci_high"] < 0.45 else ""
        print(f"  {row['utc_hour']:>5}h  {row['actual_yes_rate']*100:>7.1f}%  "
              f"  [{row['ci_low']*100:.0f}%–{row['ci_high']*100:.0f}%]  {row['n']:>5}{flag}")

    print("\n── YES Rate by Day of Week ──")
    print(f"  {'Day':>5}  {'YES%':>8}  {'CI':>16}  {'n':>5}")
    for row in report["yes_rate_by_day_of_week"]:
        flag = " ◄" if row["ci_low"] > 0.55 or row["ci_high"] < 0.45 else ""
        print(f"  {row['day']:>5}  {row['actual_yes_rate']*100:>7.1f}%  "
              f"  [{row['ci_low']*100:.0f}%–{row['ci_high']*100:.0f}%]  {row['n']:>5}{flag}")

    print("\n── YES Rate by Distance Bucket (near/mid/far from strike) ──")
    for row in report["yes_rate_by_distance_bucket"]:
        print(f"  {row['distance_bucket']:>16}  YES={row['actual_yes_rate']*100:.1f}%  "
              f"[{row['ci_low']*100:.0f}%–{row['ci_high']*100:.0f}%]  n={row['n']}")

    print("\n── Strategy Viability: Simulated PnL at Various Thresholds ──")
    print(f"  {'Threshold':>10}  {'Trades':>7}  {'WinRate':>8}  {'TotalPnL':>10}  {'AvgPnL':>8}")
    for row in report["threshold_viability"]:
        flag = " ◄ PROFITABLE" if row["total_pnl"] > 0 else ""
        print(f"  {row['threshold']*100:>9.0f}%  {row['trade_count']:>7}  "
              f"{row['win_rate']*100:>7.1f}%  {row['total_pnl']:>+10.2f}  "
              f"{row['avg_pnl']:>+8.4f}{flag}")

    if "calibrated_regime_strategy" in report:
        r = report["calibrated_regime_strategy"]
        print(f"\n── Calibrated Regime Strategy (model_prob > 0.65 or < 0.35) ──")
        print(f"  {r['description']}")
        print(f"  Trades: {r['trade_count']}  WinRate: {r['win_rate']*100:.1f}%  "
              f"TotalPnL: {r['total_pnl']:+.2f}  AvgPnL: {r['avg_pnl']:+.4f}")
        print(f"  Note: {r['note']}")

    print("\n" + "="*65)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/history_test.json",
                        help="History JSON file to analyze (default: data/history_test.json)")
    args = parser.parse_args()

    input_path = PROJECT_ROOT / args.input
    if not input_path.exists():
        print(f"ERROR: {input_path} not found. Run fetch_history.py first.")
        sys.exit(1)

    records = json.loads(input_path.read_text())
    print(f"Loaded {len(records)} records from {input_path.name}")

    report = analyze(records)
    print_report(report)

    out_path = PROJECT_ROOT / "data" / "calibration_report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nFull report saved to {out_path}")


if __name__ == "__main__":
    main()
