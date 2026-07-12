"""Phase 0: independent spot (live optional + hermetic error path)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measurement.spot import fetch_btc_spot_coinbase, fetch_btc_spot_usd


def test_spot_parse_hermetic() -> None:
    body = json.dumps({"data": {"amount": "65000.5", "base": "BTC", "currency": "USD"}}).encode()

    class Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=10):
        return Resp()

    q = fetch_btc_spot_coinbase(urlopen=fake_urlopen)
    assert q.ok
    assert q.price_usd == 65000.5
    assert q.source == "coinbase_spot"


def test_spot_fail_closed() -> None:
    def boom(req, timeout=10):
        raise TimeoutError("no net")

    q = fetch_btc_spot_coinbase(urlopen=boom)
    assert not q.ok
    assert q.error


@pytest.mark.integration
def test_live_coinbase_spot() -> None:
    q = fetch_btc_spot_usd()
    assert q.ok
    assert q.price_usd > 1000
