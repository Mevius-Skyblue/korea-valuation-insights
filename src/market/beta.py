"""Equity beta: regression of stock returns on market-index returns, Blume adjustment, Hamada unlever.

Inputs (DB): price_adj.ret_adj (adjusted daily return, see adjust.py), index_daily (ECOS 802Y001),
fs_std (debt), price_daily.mktcap (equity value).

Frequencies (window ends at the as-of date):
    daily   1 year   : one observation per trading day
    weekly  2 years  : week = Mon..Sun; return from the last trading day of the previous week
                       to the last trading day of this week (compounded daily returns)
    monthly 5 years  : same with calendar months
Formulas
    raw beta   = OLS slope of r_stock on r_market (with intercept)
    Blume      = 0.67 * raw + 0.33
    Hamada     = beta_u = beta_L / (1 + (1 - t) * D/E)       relever: beta_L = beta_u * (1 + (1 - t) * D/E)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SPECS = {"daily_1y": ("D", 1), "weekly_2y": ("W", 2), "monthly_5y": ("M", 5)}
EXPECTED_OBS = {"daily_1y": 245, "weekly_2y": 104, "monthly_5y": 60}


@dataclass
class BetaResult:
    beta: float | None
    se: float | None
    r2: float | None
    n: int
    alpha: float | None = None


def ols_beta(x: np.ndarray, y: np.ndarray) -> BetaResult:
    """Slope, its standard error and R² of y = a + b x (NaNs dropped)."""
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    n = len(x)
    if n < 3 or np.var(x) == 0:
        return BetaResult(None, None, None, n)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    b = ((x - xm) * (y - ym)).sum() / sxx
    a = ym - b * xm
    resid = y - a - b * x
    s2 = (resid**2).sum() / (n - 2)
    se = float(np.sqrt(s2 / sxx))
    sst = ((y - ym) ** 2).sum()
    r2 = float(1 - (resid**2).sum() / sst) if sst > 0 else None
    return BetaResult(float(b), se, r2, n, float(a))


def blume(raw: float | None) -> float | None:
    """Blume adjustment with the ledger's weights (config/valuation_rf.yaml beta.blume: 0.67 x raw + 0.33; P7-X2b — the
    numbers were typed here as well)."""
    if raw is None:
        return None
    from src import yamlio
    from src.collect.core import ROOT

    if not _BLUME:
        _BLUME.update(yamlio.load((ROOT / "config" / "valuation_rf.yaml").read_text(encoding="utf-8"))["beta"]["blume"])
    return _BLUME["weight_raw"] * raw + _BLUME["constant"]


_BLUME: dict = {}


def unlever(beta_l: float | None, t: float, de: float | None) -> float | None:
    if beta_l is None or de is None:
        return None
    return beta_l / (1 + (1 - t) * de)


from src.valuation.levering import relever  # noqa: E402,F401  (moved in P6-B; re-exported for existing imports)


def period_returns(daily: pd.DataFrame, freq: str) -> pd.DataFrame:
    """daily: index = date, columns = daily simple returns. Returns compounded returns per period
    labelled by the last trading date of the period (D = unchanged)."""
    if freq == "D":
        return daily
    d = daily.copy()
    idx = pd.to_datetime(d.index)
    key = idx.to_period("W-SUN") if freq == "W" else idx.to_period("M")
    g = (1 + d).groupby(key)
    out = g.prod(min_count=1) - 1
    out.index = pd.to_datetime(d.index.to_series().groupby(key).max().values)
    return out


def window_start(as_of: str, years: int) -> pd.Timestamp:
    return pd.Timestamp(as_of) - pd.DateOffset(years=years)


def stock_and_market(con, stock_code: str, index_code: str, start, end) -> pd.DataFrame:
    """Daily adjusted stock returns + index returns on our trading calendar, (start, end]."""
    s = con.execute(
        """SELECT bas_dd AS date, ret_adj, volume, flags FROM price_adj
                       WHERE stock_code = ? AND bas_dd > ? AND bas_dd <= ? ORDER BY bas_dd""",
        [stock_code, start, end],
    ).df()
    m = con.execute(
        """SELECT date, value / lag(value) OVER (ORDER BY date) - 1 AS mret FROM index_daily
                       WHERE index_code = ? AND date > ? - INTERVAL 15 DAY AND date <= ? ORDER BY date""",
        [index_code, start, end],
    ).df()
    df = s.merge(m, on="date", how="inner").set_index("date")
    return df


def estimate(con, stock_code: str, index_code: str, as_of: str, spec: str) -> dict:
    freq, years = SPECS[spec]
    start = window_start(as_of, years)
    df = stock_and_market(con, stock_code, index_code, start.date(), pd.Timestamp(as_of).date())
    rets = period_returns(df[["ret_adj", "mret"]].astype(float), freq)
    res = ols_beta(rets["mret"].to_numpy(), rets["ret_adj"].to_numpy())
    zero_share = float((df["volume"] == 0).mean()) if len(df) else None
    flags = []
    if res.r2 is not None and res.r2 < 0.1:
        flags.append("R2<0.1")
    if zero_share is not None and zero_share > 0.05:
        flags.append("zero-volume>5%")
    if res.n < 0.8 * EXPECTED_OBS[spec]:
        flags.append("few-obs")
    if df["flags"].fillna("").str.contains("market_change").any():
        flags.append("market-change")
    return {
        "stock_code": stock_code,
        "index": index_code,
        "spec": spec,
        "raw": res.beta,
        "se": res.se,
        "r2": res.r2,
        "n": res.n,
        "blume": blume(res.beta),
        "zero_volume_share": zero_share,
        "warn": ",".join(flags),
    }
