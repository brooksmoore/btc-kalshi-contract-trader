"""Phase 1 fair value — spot + short realized-vol digital (anchor A).

Prices KXBTCD threshold contracts ("Bitcoin >= $K on <date>?") as a driftless
Black-Scholes digital: P(YES) = P(S_T >= K) = N(d2), d2 = (ln(S/K) - 0.5*sigma^2*T) / (sigma*sqrt(T)),
r = 0 (short horizon, crypto has no meaningful risk-free carry over hours/days).

PURE functions, no I/O, no network — fully unit-testable. This is anchor A; per
EFFICACY_TEST_BTC_2026-07-11.md, realized vol is a BACKWARD-LOOKING point forecast and the
pre-committed successor on a floor is anchor B (options-implied). Scope: KXBTCD strike contracts
only. KXBTC15M "up in 15 min?" contracts are NOT priced here (they need the window-open reference
price, which the capture data does not carry) — the runner must skip them.
"""

from __future__ import annotations

import math
import re
from typing import Optional

_SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60

# BTC realized vol lives ~20–100% annualized. A computed vol outside these bounds means the
# spot series is degenerate (duplicate/clustered samples, uneven spacing) — NOT a real quiet
# market. Trading on such an estimate produces overconfident fair values and phantom edge (the
# exact failure that would enter dozens of markets with zero rejects). Treat out-of-band vol as
# NOT computable → no trades. Fail-closed.
MIN_PLAUSIBLE_VOL_ANNUAL = 0.10
MAX_PLAUSIBLE_VOL_ANNUAL = 3.00


def vol_is_plausible(vol_annual: Optional[float]) -> bool:
    """True only if vol is a real BTC-scale annualized number. None/degenerate -> False."""
    return (
        vol_annual is not None
        and MIN_PLAUSIBLE_VOL_ANNUAL <= vol_annual <= MAX_PLAUSIBLE_VOL_ANNUAL
    )


# digital_yes_prob clamps to [1e-6, 1-1e-6]. A value AT the clamp means the model has no real
# tail estimate (it saturated) — it cannot distinguish 1e-6 from 0.02. Trading against a
# saturated fair value is unjustified: the "edge" is an artifact of the clamp, not a view.
_SATURATION_EPS = 1e-5


def is_saturated(p_fair: Optional[float]) -> bool:
    """True if the digital saturated to (near) its clamp bounds — an unreliable estimate."""
    return p_fair is not None and (p_fair <= _SATURATION_EPS or p_fair >= 1.0 - _SATURATION_EPS)

# Strike suffix on KXBTCD tickers, e.g. "KXBTCD-26JUL1016-T71799.99" -> 71799.99
_STRIKE_RE = re.compile(r"-T(\d+(?:\.\d+)?)$")


def parse_strike(ticker: str) -> Optional[float]:
    """Strike from a KXBTCD ticker's -T<number> suffix. None if absent (e.g. KXBTC15M)."""
    m = _STRIKE_RE.search(ticker or "")
    return float(m.group(1)) if m else None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def realized_vol_annual(prices: list[float], *, interval_seconds: float) -> Optional[float]:
    """Annualized realized vol from a spot price series sampled every `interval_seconds`.

    stdev of log returns per step, scaled by sqrt(steps_per_year). None if < 3 usable points
    or non-positive prices (fail-closed — never fabricate a vol).
    """
    clean = [p for p in prices if isinstance(p, (int, float)) and p > 0]
    if len(clean) < 3 or interval_seconds <= 0:
        return None
    rets = [math.log(clean[i] / clean[i - 1]) for i in range(1, len(clean))]
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1) if n >= 2 else 0.0
    sigma_step = math.sqrt(var)
    steps_per_year = _SECONDS_PER_YEAR / interval_seconds
    return sigma_step * math.sqrt(steps_per_year)


def tte_years(now_iso_ts: float, close_ts: float) -> Optional[float]:
    """Time to expiry in years from two epoch seconds. None if non-positive (expired)."""
    dt = close_ts - now_iso_ts
    if dt <= 0:
        return None
    return dt / _SECONDS_PER_YEAR


def digital_yes_prob(
    spot: float,
    strike: float,
    tte_yr: float,
    vol_annual: float,
) -> Optional[float]:
    """P(S_T >= K) under driftless GBM = N(d2). None on degenerate inputs (fail-closed)."""
    if spot <= 0 or strike <= 0 or tte_yr <= 0 or vol_annual <= 0:
        return None
    denom = vol_annual * math.sqrt(tte_yr)
    if denom <= 0:
        return None
    d2 = (math.log(spot / strike) - 0.5 * vol_annual * vol_annual * tte_yr) / denom
    p = _norm_cdf(d2)
    # clamp away from exactly 0/1 so downstream EV math stays finite
    return min(0.999999, max(0.000001, p))
