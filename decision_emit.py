"""Umbrella decisions contract emitter for btc-bot (Phase 0 — paper capture).

Fail-safe: never raises into the capture loop.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parent
DEFAULT_DECISIONS_PATH = _BOT_ROOT / "data" / "decisions.ndjson"
BOT_ID = "btc_bot"


def decisions_path(data_dir: Path | None = None) -> Path:
    return (data_dir or _BOT_ROOT / "data") / "decisions.ndjson"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=_BOT_ROOT,
        ).strip()
    except Exception:
        return "unknown"


def _config_hash() -> str:
    cfg = _BOT_ROOT / "config" / "settings.py"
    if cfg.exists():
        return hashlib.sha256(cfg.read_bytes()).hexdigest()[:12]
    return hashlib.sha256(b"btc-default").hexdigest()[:12]


def ts_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_decision_record(
    *,
    kind: str,
    instrument: str,
    reason: str,
    mode: str = "paper",
    side: str = "buy",
    qty: float = 0.0,
    ref_price: float | None = None,
    entry_price_source: str | None = None,
    prediction: dict[str, Any] | None = None,
    actual: dict[str, Any] | None = None,
    benchmarks: dict[str, float] | None = None,
    regime: str = "phase0_capture",
    lineage: dict[str, Any] | None = None,
    ts: str | None = None,
    experiment_id: str | None = "btc-phase0-measurement",
) -> dict[str, Any]:
    ts_val = ts or ts_now()
    intended = None
    if ref_price is not None or qty:
        intended = {"side": side if side in ("buy", "sell") else "buy", "qty": float(qty)}
        if ref_price is not None:
            intended["ref_price"] = float(ref_price)

    pred = prediction or {"type": "none"}
    lin = dict(lineage or {})
    lin.setdefault("trigger", "phase0_capture")
    lin.setdefault("llm_calls", 0)
    lin.setdefault("llm_cost_usd", 0.0)
    if entry_price_source:
        lin["entry_price_source"] = entry_price_source

    tag = hashlib.sha256(
        f"{ts_val}:{instrument}:{kind}:{ref_price}:{entry_price_source}".encode()
    ).hexdigest()[:8]
    decision_id = f"btc:{ts_val}:{instrument}:{kind}:{tag}"

    return {
        "schema_version": "1.0",
        "decision_id": decision_id,
        "bot_id": BOT_ID,
        "ts": ts_val,
        "kind": kind,
        "instrument": instrument,
        "intended": intended,
        "actual": actual,
        "prediction": pred,
        "reason": (reason or "")[:280],
        "benchmarks_at_decision": benchmarks or {},
        "regime": regime,
        "lineage": lin,
        "provenance": {
            "git_sha": _git_sha(),
            "config_hash": _config_hash(),
            "prompt_hash": hashlib.sha256(b"btc-phase0-v1").hexdigest()[:12],
        },
        "mode": mode,
        "experiment_id": experiment_id,
    }


def emit_decision_safe(
    path: str | Path,
    record: dict[str, Any],
    *,
    append_fn: Optional[Callable[[str | Path, dict[str, Any]], None]] = None,
) -> bool:
    try:
        if append_fn is None:
            # bot root → btc-bot/ → Desktop/umbrella
            desktop = _BOT_ROOT.parent.parent
            umbrella = desktop / "umbrella"
            if str(umbrella) not in sys.path:
                sys.path.insert(0, str(umbrella))
            from umbrella_core.decisions import append_decision_atomic

            append_fn = append_decision_atomic
        append_fn(path, record)
        return True
    except Exception as exc:
        logger.warning("btc decision emit failed (non-fatal): %s", exc)
        return False
