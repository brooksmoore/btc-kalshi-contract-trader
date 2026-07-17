"""Anchor B pricing — Deribit BTC options → risk-neutral digital P(BTC ≷ K at T).

OBSERVE / library only. Does NOT open the Anchor-B efficacy window and does NOT emit
counted `anchor_b` umbrella decisions. That is a separate handoff after Anchor A closes
and Brooks signs off (`EFFICACY_TEST_BTC_B_2026-07-16.md`).

Primary digital: N(d2) with r=0 (crypto short-horizon convention).
Cross-check: Breeden–Litzenberger −dC/dK on the call surface.
Disagree > DISAGREE_FLAG (0.08) → flag (spike showed ~0.02 on live data).

Kalshi KXBTCD convention (as priced here):
  - YES = Bitcoin price AT OR ABOVE strike K at market close_time (threshold digital).
  - Strike from ticker suffix -T<K> (same as strategy.fair_value.parse_strike).
  - Expiry = Kalshi market close_time (UTC), not Deribit's 08:00 UTC fixed cycle.
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from strategy.fair_value import parse_strike

log = logging.getLogger("anchor_b_pricing")

DERIBIT_BASE = "https://www.deribit.com/api/v2"
_SECONDS_PER_YEAR = 365.25 * 24 * 3600

# Flag if N(d2) and −dC/dK disagree by more than this (spike: ~0.02).
DISAGREE_FLAG = 0.08

# Fail-closed: index/chain older than this is unusable.
MAX_CHAIN_AGE_SEC = 120.0

# Plausible BTC IV bounds (annualized decimal, e.g. 0.30 = 30%).
MIN_IV = 0.05
MAX_IV = 3.00


# ── pure math ────────────────────────────────────────────────────────────────


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def tte_years(now_ts: float, expiry_ts: float) -> Optional[float]:
    dt = expiry_ts - now_ts
    if dt <= 0:
        return None
    return dt / _SECONDS_PER_YEAR


def digital_n_d2(
    spot: float,
    strike: float,
    tte_yr: float,
    vol_annual: float,
    *,
    above: bool = True,
) -> Optional[float]:
    """Risk-neutral P(S_T >= K) = N(d2) under r=0 GBM. If above=False, return P(S_T < K)."""
    if spot <= 0 or strike <= 0 or tte_yr <= 0 or vol_annual <= 0:
        return None
    denom = vol_annual * math.sqrt(tte_yr)
    if denom <= 0:
        return None
    d2 = (math.log(spot / strike) - 0.5 * vol_annual * vol_annual * tte_yr) / denom
    p_above = _norm_cdf(d2)
    p_above = min(0.999999, max(0.000001, p_above))
    return p_above if above else (1.0 - p_above)


def bs_call_price(
    spot: float,
    strike: float,
    tte_yr: float,
    vol_annual: float,
    *,
    r: float = 0.0,
) -> Optional[float]:
    """Black–Scholes call (USD). r=0 by default for short crypto horizon."""
    if spot <= 0 or strike <= 0 or tte_yr <= 0 or vol_annual <= 0:
        return None
    sqrt_t = math.sqrt(tte_yr)
    denom = vol_annual * sqrt_t
    if denom <= 0:
        return None
    d1 = (math.log(spot / strike) + (r + 0.5 * vol_annual * vol_annual) * tte_yr) / denom
    d2 = d1 - denom
    return spot * _norm_cdf(d1) - strike * math.exp(-r * tte_yr) * _norm_cdf(d2)


def breeden_litzenberger_digital(
    call_lo: float,
    call_hi: float,
    strike_lo: float,
    strike_hi: float,
    *,
    above: bool = True,
) -> Optional[float]:
    """P(S_T > K) ≈ −dC/dK from two nearby call prices (finite difference).

    For a continuum of European calls, risk-neutral density f(K)=e^{rT} d²C/dK²;
    the digital (cash-or-nothing above K) is −dC/dK (r=0). Uses midpoint K.
    """
    dk = strike_hi - strike_lo
    if dk <= 0:
        return None
    # −dC/dK ≈ −(C_hi − C_lo)/dk
    dig = -(call_hi - call_lo) / dk
    # numerical noise can push slightly outside [0,1]
    dig = min(1.0, max(0.0, dig))
    return dig if above else (1.0 - dig)


def interpolate_scalar(
    x: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    allow_extrapolate: bool = False,
) -> Optional[float]:
    """Linear interpolation. Fail-closed outside [x0,x1] unless allow_extrapolate."""
    if x0 == x1:
        return y0 if abs(x - x0) < 1e-12 else None
    # order endpoints
    if x0 > x1:
        x0, x1 = x1, x0
        y0, y1 = y1, y0
    if not allow_extrapolate and (x < x0 - 1e-12 or x > x1 + 1e-12):
        return None
    w = (x - x0) / (x1 - x0)
    return y0 + w * (y1 - y0)


def interpolate_iv_term(
    t_target: float,
    t0: float,
    iv0: float,
    t1: float,
    iv1: float,
) -> Optional[float]:
    """Interpolate IV in total-variance space between two expiries, then back to IV.

    total_var = iv^2 * T. Linear in total_var is standard and avoids blowups.
    If t_target equals an anchor, return that IV. Outside span → None (fail-closed).
    """
    if t_target <= 0 or t0 <= 0 or t1 <= 0:
        return None
    if iv0 <= 0 or iv1 <= 0:
        return None
    if abs(t_target - t0) < 1e-12:
        return iv0
    if abs(t_target - t1) < 1e-12:
        return iv1
    # order
    if t0 > t1:
        t0, t1 = t1, t0
        iv0, iv1 = iv1, iv0
    if t_target < t0 or t_target > t1:
        return None
    tv0 = iv0 * iv0 * t0
    tv1 = iv1 * iv1 * t1
    tv = interpolate_scalar(t_target, t0, tv0, t1, tv1)
    if tv is None or tv <= 0:
        return None
    return math.sqrt(tv / t_target)


def interpolate_iv_smile(
    strike: float,
    strikes: list[float],
    ivs: list[float],
) -> Optional[float]:
    """Linear IV smile interpolation in strike. Fail-closed outside range."""
    if len(strikes) != len(ivs) or len(strikes) < 1:
        return None
    pairs = sorted(
        [(float(k), float(v)) for k, v in zip(strikes, ivs) if k > 0 and v and MIN_IV <= v <= MAX_IV],
        key=lambda p: p[0],
    )
    if not pairs:
        return None
    if len(pairs) == 1:
        return pairs[0][1] if abs(strike - pairs[0][0]) < 1e-6 else None
    ks = [p[0] for p in pairs]
    vs = [p[1] for p in pairs]
    if strike < ks[0] or strike > ks[-1]:
        return None
    for i in range(len(ks) - 1):
        if ks[i] <= strike <= ks[i + 1]:
            return interpolate_scalar(strike, ks[i], vs[i], ks[i + 1], vs[i + 1])
    return None


# ── chain structures ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OptionQuote:
    instrument: str
    expiry_ts: float  # unix seconds
    strike: float
    option_type: str  # "call" | "put"
    mark_iv: float  # annualized decimal
    mark_price_btc: float  # Deribit mark in BTC
    mark_price_usd: float  # mark_price_btc * index


@dataclass
class DeribitChain:
    index_usd: float
    fetched_ts: float
    options: list[OptionQuote] = field(default_factory=list)
    source: str = "deribit_public"
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.index_usd > 0
            and len(self.options) > 0
            and (time.time() - self.fetched_ts) <= MAX_CHAIN_AGE_SEC
        )

    def age_sec(self) -> float:
        return max(0.0, time.time() - self.fetched_ts)


@dataclass(frozen=True)
class DigitalQuote:
    """Risk-neutral digital for one Kalshi-style threshold event."""
    ok: bool
    p_yes: Optional[float]  # P(BTC >= K) at expiry — Kalshi YES for KXBTCD
    p_n_d2: Optional[float]
    p_bl: Optional[float]  # Breeden–Litzenberger cross-check
    iv_used: Optional[float]
    spot: Optional[float]
    strike: float
    expiry_ts: float
    tte_years: Optional[float]
    disagree: Optional[float]
    disagree_flag: bool
    method: str
    error: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ── Deribit fetch ────────────────────────────────────────────────────────────


def _ssl_context():
    """Prefer certifi CA bundle (macOS system Python often lacks a CA store)."""
    try:
        import ssl
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            import ssl
            return ssl.create_default_context()
        except Exception:
            return None


def _http_get_json(
    url: str,
    *,
    timeout_sec: float = 15.0,
    urlopen: Callable = urllib.request.urlopen,
) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "btc-bot-anchor-b/1.0"})
    ctx = _ssl_context()
    # urlopen accepts context= when using default opener; inject via opener if needed
    if ctx is not None and urlopen is urllib.request.urlopen:
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    with urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_deribit_chain(
    *,
    timeout_sec: float = 20.0,
    urlopen: Callable = urllib.request.urlopen,
) -> DeribitChain:
    """Pull BTC index + option book summaries. Public endpoints, no key.

    Fail-closed: any error → DeribitChain with error set and ok=False.
    """
    t0 = time.time()
    try:
        idx_url = f"{DERIBIT_BASE}/public/get_index_price?index_name=btc_usd"
        idx_raw = _http_get_json(idx_url, timeout_sec=timeout_sec, urlopen=urlopen)
        index = float((idx_raw.get("result") or {}).get("index_price") or 0)
        if index <= 0:
            raise ValueError(f"bad index_price: {idx_raw}")

        book_url = (
            f"{DERIBIT_BASE}/public/get_book_summary_by_currency"
            f"?currency=BTC&kind=option"
        )
        book_raw = _http_get_json(book_url, timeout_sec=timeout_sec, urlopen=urlopen)
        rows = book_raw.get("result") or []
        if not isinstance(rows, list) or not rows:
            raise ValueError("empty option book summary")

        options: list[OptionQuote] = []
        for row in rows:
            try:
                name = str(row.get("instrument_name") or "")
                # BTC-17JUL26-65000-C
                parts = name.split("-")
                if len(parts) < 4:
                    continue
                opt_type = parts[-1].lower()
                if opt_type not in ("c", "p", "call", "put"):
                    continue
                option_type = "call" if opt_type in ("c", "call") else "put"
                strike = float(parts[-2])
                # expiry from Deribit field if present
                exp_ms = row.get("creation_timestamp")  # not expiry
                # Prefer explicit expiration; book summary often has none — parse date
                expiry_ts = _parse_deribit_expiry(parts[1], now=t0)
                if expiry_ts is None:
                    continue
                mark_iv_raw = row.get("mark_iv")
                if mark_iv_raw is None:
                    continue
                mark_iv = float(mark_iv_raw)
                # Deribit mark_iv is percent (e.g. 32.9) — convert to decimal
                if mark_iv > 3.0:  # clearly percent
                    mark_iv = mark_iv / 100.0
                if not (MIN_IV <= mark_iv <= MAX_IV):
                    continue
                mark_btc = float(row.get("mark_price") or 0)
                mark_usd = mark_btc * index
                options.append(
                    OptionQuote(
                        instrument=name,
                        expiry_ts=expiry_ts,
                        strike=strike,
                        option_type=option_type,
                        mark_iv=mark_iv,
                        mark_price_btc=mark_btc,
                        mark_price_usd=mark_usd,
                    )
                )
            except (TypeError, ValueError, KeyError):
                continue

        if not options:
            raise ValueError("no usable option quotes after parse")

        return DeribitChain(
            index_usd=index,
            fetched_ts=t0,
            options=options,
            source="deribit_public",
        )
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Deribit chain fetch failed (fail-closed): %s", exc)
        return DeribitChain(
            index_usd=0.0,
            fetched_ts=t0,
            options=[],
            error=str(exc),
        )


_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _parse_deribit_expiry(token: str, *, now: float) -> Optional[float]:
    """Parse '17JUL26' → unix ts at 08:00 UTC (Deribit standard)."""
    token = (token or "").upper()
    if len(token) < 7:
        return None
    try:
        day = int(token[:2])
        mon = _MONTHS.get(token[2:5])
        year = int(token[5:7])
        if mon is None:
            return None
        year += 2000
        dt = datetime(year, mon, day, 8, 0, 0, tzinfo=timezone.utc)
        ts = dt.timestamp()
        return ts
    except (ValueError, TypeError):
        return None


def _expiries_with_calls(chain: DeribitChain) -> dict[float, list[OptionQuote]]:
    by_exp: dict[float, list[OptionQuote]] = {}
    for o in chain.options:
        if o.option_type != "call":
            continue
        by_exp.setdefault(o.expiry_ts, []).append(o)
    return by_exp


def _iv_at_strike_for_expiry(
    calls: list[OptionQuote],
    strike: float,
) -> Optional[float]:
    strikes = [c.strike for c in calls]
    ivs = [c.mark_iv for c in calls]
    return interpolate_iv_smile(strike, strikes, ivs)


def price_digital_from_chain(
    chain: DeribitChain,
    *,
    strike: float,
    expiry_ts: float,
    now_ts: Optional[float] = None,
    above: bool = True,
) -> DigitalQuote:
    """Core pricing: interpolate IV to (K, T), N(d2) primary + BL cross-check.

    Fail-closed on missing/stale chain or interpolation failure → ok=False, p_yes=None.
    """
    now = now_ts if now_ts is not None else time.time()
    base = DigitalQuote(
        ok=False,
        p_yes=None,
        p_n_d2=None,
        p_bl=None,
        iv_used=None,
        spot=None,
        strike=float(strike),
        expiry_ts=float(expiry_ts),
        tte_years=None,
        disagree=None,
        disagree_flag=False,
        method="n_d2+bl",
    )
    if chain.error or chain.index_usd <= 0 or not chain.options:
        return DigitalQuote(**{**asdict(base), "error": chain.error or "empty/bad chain"})
    age = now - chain.fetched_ts
    if age > MAX_CHAIN_AGE_SEC:
        return DigitalQuote(**{**asdict(base), "error": f"stale chain age_sec={age:.1f}"})

    tte = tte_years(now, expiry_ts)
    if tte is None:
        return DigitalQuote(**{**asdict(base), "error": "expired or bad TTE"})

    by_exp = _expiries_with_calls(chain)
    if not by_exp:
        return DigitalQuote(**{**asdict(base), "error": "no call quotes"})

    exp_list = sorted(by_exp.keys())
    # pick bracketing expiries for term structure
    iv_target: Optional[float] = None
    term_note = ""
    if expiry_ts in by_exp or any(abs(e - expiry_ts) < 60 for e in exp_list):
        # exact or within 1 min
        e_exact = min(exp_list, key=lambda e: abs(e - expiry_ts))
        iv_target = _iv_at_strike_for_expiry(by_exp[e_exact], strike)
        term_note = "exact_expiry"
    else:
        below = [e for e in exp_list if e < expiry_ts]
        above_e = [e for e in exp_list if e > expiry_ts]
        if below and above_e:
            e0, e1 = max(below), min(above_e)
            t0 = tte_years(now, e0)
            t1 = tte_years(now, e1)
            iv0 = _iv_at_strike_for_expiry(by_exp[e0], strike)
            iv1 = _iv_at_strike_for_expiry(by_exp[e1], strike)
            if t0 and t1 and iv0 and iv1:
                iv_target = interpolate_iv_term(tte, t0, iv0, t1, iv1)
                term_note = f"term_interp {e0}->{e1}"
        elif below:
            # nearest shorter only — fail-closed on pure extrapolation past last
            # Use nearest expiry only if within 3 days; else None
            e0 = max(below)
            if abs(e0 - expiry_ts) <= 3 * 86400:
                iv_target = _iv_at_strike_for_expiry(by_exp[e0], strike)
                term_note = "nearest_below_le_3d"
        elif above_e:
            e1 = min(above_e)
            if abs(e1 - expiry_ts) <= 3 * 86400:
                iv_target = _iv_at_strike_for_expiry(by_exp[e1], strike)
                term_note = "nearest_above_le_3d"

    if iv_target is None or not (MIN_IV <= iv_target <= MAX_IV):
        return DigitalQuote(
            **{
                **asdict(base),
                "tte_years": tte,
                "spot": chain.index_usd,
                "error": f"IV interpolation failed ({term_note or 'no anchors'})",
            }
        )

    p_nd2 = digital_n_d2(chain.index_usd, strike, tte, iv_target, above=above)
    if p_nd2 is None:
        return DigitalQuote(
            **{
                **asdict(base),
                "tte_years": tte,
                "spot": chain.index_usd,
                "iv_used": iv_target,
                "error": "N(d2) failed",
            }
        )

    # Breeden–Litzenberger: use nearest expiry's call marks around K
    p_bl: Optional[float] = None
    e_for_bl = min(exp_list, key=lambda e: abs(e - expiry_ts))
    calls = sorted(by_exp[e_for_bl], key=lambda c: c.strike)
    # find two strikes bracketing K
    for i in range(len(calls) - 1):
        if calls[i].strike <= strike <= calls[i + 1].strike:
            c0, c1 = calls[i], calls[i + 1]
            # Prefer USD marks; if mark is 0, synthesize BS call at each strike's IV
            c0_usd = c0.mark_price_usd
            c1_usd = c1.mark_price_usd
            if c0_usd <= 0:
                c0_usd = bs_call_price(chain.index_usd, c0.strike, tte_years(now, e_for_bl) or tte, c0.mark_iv) or 0
            if c1_usd <= 0:
                c1_usd = bs_call_price(chain.index_usd, c1.strike, tte_years(now, e_for_bl) or tte, c1.mark_iv) or 0
            # Scale call prices if T differs: use BS at target T with interpolated IV for denser check
            # For cross-check at *target* K,T: finite difference of BS calls at K±dk with iv_target
            dk = max(50.0, 0.005 * strike)  # ~0.5% strike step or $50
            c_lo = bs_call_price(chain.index_usd, strike - dk, tte, iv_target)
            c_hi = bs_call_price(chain.index_usd, strike + dk, tte, iv_target)
            if c_lo is not None and c_hi is not None:
                p_bl = breeden_litzenberger_digital(c_lo, c_hi, strike - dk, strike + dk, above=above)
            break
    if p_bl is None:
        # pure BS finite difference even without bracketing market strikes
        dk = max(50.0, 0.005 * strike)
        c_lo = bs_call_price(chain.index_usd, strike - dk, tte, iv_target)
        c_hi = bs_call_price(chain.index_usd, strike + dk, tte, iv_target)
        if c_lo is not None and c_hi is not None:
            p_bl = breeden_litzenberger_digital(c_lo, c_hi, strike - dk, strike + dk, above=above)

    disagree = abs(p_nd2 - p_bl) if p_bl is not None else None
    flag = bool(disagree is not None and disagree > DISAGREE_FLAG)

    return DigitalQuote(
        ok=True,
        p_yes=p_nd2,  # primary is N(d2); Kalshi YES = above for KXBTCD
        p_n_d2=p_nd2,
        p_bl=p_bl,
        iv_used=iv_target,
        spot=chain.index_usd,
        strike=float(strike),
        expiry_ts=float(expiry_ts),
        tte_years=tte,
        disagree=disagree,
        disagree_flag=flag,
        method="n_d2+bl",
        error=None,
        extra={"term": term_note, "bl_expiry_ts": e_for_bl},
    )


def price_kalshi_kxbtcd(
    chain: DeribitChain,
    *,
    ticker: str,
    close_time: str,
    now_ts: Optional[float] = None,
) -> DigitalQuote:
    """Price a Kalshi KXBTCD 'Bitcoin above K by close_time' digital.

    YES = P(S_T >= K). Strike from ticker; expiry from close_time ISO.
    """
    strike = parse_strike(ticker)
    if strike is None:
        return DigitalQuote(
            ok=False,
            p_yes=None,
            p_n_d2=None,
            p_bl=None,
            iv_used=None,
            spot=None,
            strike=0.0,
            expiry_ts=0.0,
            tte_years=None,
            disagree=None,
            disagree_flag=False,
            method="n_d2+bl",
            error="no strike (non-KXBTCD)",
        )
    try:
        exp = datetime.fromisoformat(close_time.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return DigitalQuote(
            ok=False,
            p_yes=None,
            p_n_d2=None,
            p_bl=None,
            iv_used=None,
            spot=None,
            strike=float(strike),
            expiry_ts=0.0,
            tte_years=None,
            disagree=None,
            disagree_flag=False,
            method="n_d2+bl",
            error=f"bad close_time {close_time!r}",
        )
    return price_digital_from_chain(
        chain, strike=strike, expiry_ts=exp, now_ts=now_ts, above=True,
    )


def synthetic_flat_vol_chain(
    *,
    spot: float,
    vol: float,
    expiry_ts: float,
    strikes: list[float],
    now_ts: float,
) -> DeribitChain:
    """Build a hermetic flat-vol call chain for unit tests (no network)."""
    tte = tte_years(now_ts, expiry_ts)
    assert tte is not None and tte > 0
    options: list[OptionQuote] = []
    for k in strikes:
        c = bs_call_price(spot, k, tte, vol) or 0.0
        options.append(
            OptionQuote(
                instrument=f"BTC-SYN-{int(k)}-C",
                expiry_ts=expiry_ts,
                strike=float(k),
                option_type="call",
                mark_iv=vol,
                mark_price_btc=c / spot if spot else 0.0,
                mark_price_usd=c,
            )
        )
    return DeribitChain(index_usd=spot, fetched_ts=now_ts, options=options, source="synthetic")
