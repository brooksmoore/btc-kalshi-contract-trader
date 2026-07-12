"""Emit the umbrella canonical snapshot for btc-bot (read-only)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:  # Python < 3.11
    UTC = timezone.utc
from pathlib import Path

from umbrella_core.emit import (
    AccountInfo,
    CapitalInfo,
    ComputeInfo,
    HealthInfo,
    IdentityInfo,
    LifecycleInfo,
    PositionInfo,
    Snapshot,
    TimingInfo,
    snapshot_to_dict,
    write_snapshot_atomic,
)
from umbrella_core.snapshot import validate_snapshot

from config.settings import Settings

log = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parent
_ARTIFACT_WARNING = (
    "backtest win rate (~97%) is a known measurement artifact — scored against "
    "the bot's own modeled prices, not an independent feed; not valid evidence"
)
_LIVENESS_SEC = 120  # SCAN_INTERVAL_SECONDS default when running


def _last_log_activity() -> str | None:
    log_path = _BOT_ROOT / "logs" / "bot.log"
    if not log_path.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC)
        return mtime.isoformat()
    except OSError:
        return None


def build_btc_snapshot(
    settings: Settings | None = None,
    *,
    killed: bool = True,
    cycle_at: datetime | None = None,
) -> Snapshot:
    """Map btc-bot state to the umbrella canonical snapshot (honest, no fake alpha)."""
    cfg = settings or Settings()
    now = cycle_at or datetime.now(UTC)
    starting = float(cfg.STARTING_BANKROLL)
    last_cycle = _last_log_activity() or now.isoformat()

    broker_label = f"kalshi-{cfg.KALSHI_ENV}"
    warnings = [
        "bot not running — blocked on real independent BTC price feed",
        _ARTIFACT_WARNING,
    ]

    return Snapshot(
        schema_version="1.0",
        identity=IdentityInfo(
            bot_id="btc_bot",
            display_name="BTC 5-Minute Contract Trader",
            membrane="independent",
            account=AccountInfo(broker=broker_label),
            asset_classes=["event_contract", "crypto"],
            strategy="Kalshi BTC bracket contracts — ensemble of momentum/mean-reversion/CVD strategies",
        ),
        lifecycle=LifecycleInfo(
            stage="core-done",
            mode="paper",
            live_gate="disarmed",
            killed=killed,
            cadence="continuous",
            expected_update_interval_sec=_LIVENESS_SEC,
        ),
        timing=TimingInfo(
            generated_at=now.isoformat(),
            last_cycle_at=last_cycle,
            last_fill_at=None,
        ),
        capital=CapitalInfo(
            base_currency="USD",
            own_nav=starting,
            cash=starting,
            invested=0.0,
            budget_allocation=starting,
            day_pnl=None,
            total_pnl=None,
        ),
        positions=[],
        compute=ComputeInfo(
            llm_spend_today_usd=0.0,
            llm_budget_usd=0.0,
            budget_remaining_usd=0.0,
            calls_today=0,
            breaker_tripped=True,
        ),
        health=HealthInfo(
            overall="down",  # type: ignore[arg-type]
            sources={
                "kalshi": "n/a",
                "price_feed": "down",
                "ledger": "n/a",
            },
            warnings=warnings,
        ),
        extra={
            "evidence_status": "invalid_pending_real_price_feed",
            "measurement_artifact": {
                "claimed_backtest_win_rate": None,
                "note": _ARTIFACT_WARNING,
                "do_not_treat_as_validated": True,
            },
            "decisions_path": str(_BOT_ROOT / "data" / "decisions.ndjson"),
            "runner": "stopped",
        },
    )


def emit_btc_snapshot(
    out_path: Path,
    settings: Settings | None = None,
    *,
    killed: bool = True,
    cycle_at: datetime | None = None,
) -> bool:
    """Validate and atomically write state.json. Keeps prior file on validation failure."""
    snapshot = build_btc_snapshot(settings, killed=killed, cycle_at=cycle_at)
    payload = snapshot_to_dict(snapshot)
    errors = validate_snapshot(payload)
    if errors:
        log.error(
            "umbrella snapshot validation failed; keeping prior %s: %s",
            out_path,
            errors,
        )
        return False
    write_snapshot_atomic(out_path, payload)
    log.info("umbrella snapshot written to %s", out_path)
    return True