"""Kalshi fee model — pure functions, no I/O.

Pinned conventions (Phase 0):
  - Contract price P in [0, 1] (dollars of probability, not cents).
  - Fees in USD per contract.
  - Taker: round(mult * P * (1-P), 4) with default mult=0.07 (standard schedule).
  - Maker: round(maker_mult * P * (1-P), 4) with default maker_mult=0.0175.
  - Crypto series may use a higher multiplier — set CRYPTO_TAKER_MULT via arg/env
    once confirmed from live fee schedule for the series you trade.
  - No settlement fee in current public schedule (fee=0); parameter kept for honesty.

References: Kalshi fee schedule formula peak at P=0.50.
"""

from __future__ import annotations

import math
from typing import Literal

# Standard public formula multipliers (USD per contract, P in 0..1)
DEFAULT_TAKER_MULT = 0.07
DEFAULT_MAKER_MULT = 0.0175
# Conservative crypto headroom until series multiplier confirmed live
DEFAULT_CRYPTO_TAKER_MULT = 0.07  # raise only when fee schedule proves elevated
SETTLEMENT_FEE_USD = 0.0  # public schedule: no settlement fee (re-verify per series)


def _clamp_price(price: float) -> float:
    if price < 0 or price > 1:
        # Accept cents 0..100 and convert once
        if 1 < price <= 100:
            price = price / 100.0
        else:
            raise ValueError(f"price must be in [0,1] or cents (0,100], got {price}")
    return float(price)


def taker_fee_per_contract(
    price: float,
    *,
    mult: float = DEFAULT_TAKER_MULT,
    contracts: int = 1,
) -> float:
    """Taker fee in USD for `contracts` at price P."""
    p = _clamp_price(price)
    if contracts < 1:
        raise ValueError("contracts must be >= 1")
    per = round(mult * p * (1.0 - p), 4)
    return round(per * contracts, 4)


def maker_fee_per_contract(
    price: float,
    *,
    mult: float = DEFAULT_MAKER_MULT,
    contracts: int = 1,
) -> float:
    """Maker fee in USD for `contracts` at price P."""
    p = _clamp_price(price)
    if contracts < 1:
        raise ValueError("contracts must be >= 1")
    per = round(mult * p * (1.0 - p), 4)
    return round(per * contracts, 4)


def fee_for_role(
    price: float,
    role: Literal["taker", "maker"],
    *,
    taker_mult: float = DEFAULT_TAKER_MULT,
    maker_mult: float = DEFAULT_MAKER_MULT,
    contracts: int = 1,
) -> float:
    if role == "taker":
        return taker_fee_per_contract(price, mult=taker_mult, contracts=contracts)
    if role == "maker":
        return maker_fee_per_contract(price, mult=maker_mult, contracts=contracts)
    raise ValueError(f"unknown role {role}")


def net_ev_per_contract(
    *,
    win_prob: float,
    entry_price: float,
    side: Literal["yes", "no"] = "yes",
    role: Literal["taker", "maker"] = "taker",
    taker_mult: float = DEFAULT_TAKER_MULT,
    maker_mult: float = DEFAULT_MAKER_MULT,
    settlement_fee: float = SETTLEMENT_FEE_USD,
) -> float:
    """Expected net PnL per contract after fees (fractional dollars).

    YES long at entry_price: + (1 - entry) on win, -entry on loss, minus fees.
    win_prob is P(YES settles). For NO side, use 1-win_prob and no entry price.
    """
    p = _clamp_price(entry_price)
    w = float(win_prob)
    if not 0 <= w <= 1:
        raise ValueError("win_prob must be in [0,1]")
    fee = fee_for_role(p, role, taker_mult=taker_mult, maker_mult=maker_mult, contracts=1)
    if side == "yes":
        gross = w * (1.0 - p) + (1.0 - w) * (-p)
    else:
        # buy NO at p_no: win when YES loses
        gross = (1.0 - w) * (1.0 - p) + w * (-p)
    # settlement fee charged on winning contracts in some models; schedule = 0
    settle = settlement_fee * (w if side == "yes" else (1.0 - w))
    return round(gross - fee - settle, 6)


def fee_peak_price() -> float:
    """Price that maximizes P*(1-P) fee shape."""
    return 0.5
