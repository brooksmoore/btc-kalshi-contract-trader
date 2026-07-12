"""Auditor-owned gate: btc-bot umbrella snapshot validates."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

_BOT_ROOT = Path(__file__).resolve().parents[1]
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

from snapshot_emit import build_btc_snapshot, emit_btc_snapshot
from umbrella_core.emit import snapshot_to_dict
from umbrella_core.snapshot import validate_snapshot

_TS = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


def test_emitted_snapshot_validates() -> None:
    snap = build_btc_snapshot(killed=True, cycle_at=_TS)
    errors = validate_snapshot(snapshot_to_dict(snap))
    assert errors == [], "\n".join(errors)


def test_stopped_bot_no_validated_results() -> None:
    snap = build_btc_snapshot(killed=True, cycle_at=_TS)
    assert snap.lifecycle.killed is True
    assert snap.lifecycle.mode == "paper"
    assert snap.lifecycle.live_gate == "disarmed"
    assert snap.health.overall == "down"
    assert snap.capital.total_pnl is None
    assert snap.capital.day_pnl is None
    assert snap.positions == []
    artifact = snap.extra.get("measurement_artifact", {})
    assert artifact.get("do_not_treat_as_validated") is True
    assert any("artifact" in w.lower() for w in snap.health.warnings)


def test_validation_failure_does_not_overwrite_good_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out_path = tmp_path / "state.json"
    assert emit_btc_snapshot(out_path, killed=True, cycle_at=_TS)
    good_bytes = out_path.read_bytes()

    broken = build_btc_snapshot(killed=True, cycle_at=_TS)
    broken.health.overall = "not-a-real-status"  # type: ignore[misc]

    with patch("snapshot_emit.build_btc_snapshot", return_value=broken):
        assert not emit_btc_snapshot(out_path, killed=True, cycle_at=_TS)

    assert out_path.read_bytes() == good_bytes
    assert any("validation failed" in r.message.lower() for r in caplog.records)