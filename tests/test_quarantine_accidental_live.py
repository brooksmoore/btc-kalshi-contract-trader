"""Quarantine legacy live channel (Grok handoff 2026-07-16).

A1: run_bot prod without --paper hard-refuses (no Trader, SystemExit).
A2: Trader(paper_trade=False) requires BTC_LIVE_CONFIRM=ARM-REAL-MONEY.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_run_bot_module():
    """Load deploy/run_bot.py as a module without executing main."""
    path = ROOT / "deploy" / "run_bot.py"
    spec = importlib.util.spec_from_file_location("btc_run_bot_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # run_bot pulls monitoring.* — may fail without full deps; import only the
    # refuse helper by exec of a minimal slice if needed.
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        # Fallback: define refuse from source by importing trader path only
        # and re-implementing the pure helper under test via import of a
        # thin shared path — here we read and exec just refuse_legacy_live
        # by importing bot.trader is separate. For A1, exec the function body.
        ns: dict = {}
        code = (path).read_text(encoding="utf-8")
        # Extract refuse_legacy_live by compiling after injecting sys
        start = code.index("def refuse_legacy_live")
        end = code.index("async def main")
        snippet = "import sys\n" + code[start:end]
        exec(snippet, ns)  # noqa: S102 — test isolation of pure helper
        return SimpleNamespace(refuse_legacy_live=ns["refuse_legacy_live"])


def test_a1_legacy_prod_without_paper_refuses() -> None:
    mod = _load_run_bot_module()
    with pytest.raises(SystemExit) as ei:
        mod.refuse_legacy_live(env="prod", paper=False)
    assert ei.value.code == 2


def test_a1_paper_prod_allowed() -> None:
    """--env prod --paper is paper mode (simulated fills); refuse only pure live."""
    mod = _load_run_bot_module()
    mod.refuse_legacy_live(env="prod", paper=True)  # no raise
    mod.refuse_legacy_live(env="demo", paper=False)


def _load_trader_class():
    """Load bot/trader.py without bot package __init__ (aiosqlite etc.)."""
    path = ROOT / "bot" / "trader.py"
    name = "btc_trader_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.Trader


def test_a2_trader_live_refuses_without_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BTC_LIVE_CONFIRM", raising=False)
    Trader = _load_trader_class()

    client = SimpleNamespace(paper_trade=False)
    with pytest.raises(RuntimeError, match="BTC_LIVE_CONFIRM"):
        Trader(
            kalshi_client=client,
            strategy=object(),
            risk_manager=object(),
            order_manager=object(),
            position_tracker=object(),
            settings={},
            paper_trade=False,
        )


def test_a2_trader_live_constructs_with_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BTC_LIVE_CONFIRM", "ARM-REAL-MONEY")
    Trader = _load_trader_class()

    t = Trader(
        kalshi_client=SimpleNamespace(paper_trade=False),
        strategy=object(),
        risk_manager=object(),
        order_manager=object(),
        position_tracker=object(),
        settings={},
        paper_trade=False,
    )
    assert t.paper_trade is False


def test_a2_trader_paper_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BTC_LIVE_CONFIRM", raising=False)
    Trader = _load_trader_class()

    t = Trader(
        kalshi_client=SimpleNamespace(paper_trade=True),
        strategy=object(),
        risk_manager=object(),
        order_manager=object(),
        position_tracker=object(),
        settings={},
        paper_trade=True,
    )
    assert t.paper_trade is True
