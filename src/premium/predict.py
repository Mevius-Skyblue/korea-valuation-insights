"""Conditional control-premium range for a target company (P2-C C3; design in config/premium_p2c3.yaml).

premium_range(mktcap_pct, stake_band, buyer_group, market, period) returns
  - q25 / q50 / q75 chosen by the pre-registered rule (config/premium_p2c3.yaml): the quantile regression if its 5-fold
    CV q50 pinball loss improves >= 5% on the unconditional median, otherwise the 20-point percentile band table of the
    market. C3 (2026-10-02): 5.7% -> regression adopted. C4 data fixes: 4.7% -> band table (method field).
    P2.6 fixes (2026-10-03): 3.9% -> band table (20 other CV seeds: 3.9~5.8%, reference only)
    D6 application rule (user decision 2026-10-03, config/premium_p2c3.yaml `application_rule`): KOSPI -> neighbours
    (rule_market), KOSDAQ percentile >= 80 -> neighbours (rule_top_band), regression with the gap warning -> neighbours
    (warning); otherwise the CV rule above (regression / band table). `method` and `reason` say which one was used
  - the regression values are always returned for reference
  - the 50 nearest deals by market-cap percentile (same market first): q25 / q50 / q75 and n
  - the 20-point percentile band table of the market (fallback table)
  - warnings: extrapolation (percentile outside the market's sample range), cell n < 10, |regression q50 -
    neighbour median| > 10 %p (pre-registered warning)
Premium = price / bu20_doc - 1 (documented-signal unaffected 20-day VWAP). Ranges, not a point estimate.

mktcap_percentile(con, date, market, mktcap) gives the percentile of a market cap on a date among the common
stocks of that market (same universe rule as the sample). Not run for RF머트리얼즈 here (P3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from src.premium.p2c3 import ELIGIBLE_SQL, QS, fit_qr, neighbours, predict_qr, quintile_band

STAKE_BANDS = ("lt25", "25to50", "gt50")
BUYER_GROUPS = ("strategic", "financial", "other")
PERIODS = {"2010-2014": 1, "2015-2026": 0, "early": 1, "late": 0}
GAP_WARN = 0.10
K = 50


@dataclass
class PremiumRange:
    q25: float
    q50: float
    q75: float
    method: str  # regression / neighbours / band_table (D6 application rule)
    regression: dict
    neighbour: dict
    band: dict
    warnings: list[str] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)
    cv_improvement_q50: float | None = None
    reason: str = ""  # rule_market / rule_top_band / warning / cv_adopted / cv_not_adopted


def percentile_from_universe(caps: pd.Series, x: float) -> float:
    """Mid-rank percentile (0-100) of x in the universe of market caps."""
    c = pd.Series(caps, dtype=float).dropna()
    return float(100 * ((c < x).sum() + 0.5 * (c == x).sum()) / len(c))


def mktcap_percentile(con, date, market: str, mktcap: float) -> dict:
    """Percentile of `mktcap` on `date` among common stocks of `market` (KRX file of that day only)."""
    u = con.execute(
        f"""
        SELECT coalesce(mf.mktcap_fix, d.mktcap) AS mktcap, {ELIGIBLE_SQL} AS eligible
        FROM price_daily d LEFT JOIN (SELECT DISTINCT stock_code, kind_stkcert, secugrp_nm FROM corp_master) cm
             ON cm.stock_code = d.stock_code
        LEFT JOIN mktcap_fix mf ON mf.stock_code = d.stock_code AND mf.bas_dd = d.bas_dd
        WHERE d.bas_dd = ? AND d.mkt_nm = ?""",
        [date, market],
    ).fetchdf()
    e = u[u.eligible]
    if e.empty:
        raise ValueError(f"no {market} rows on {date} (not a trading day?)")
    return {
        "mktcap_pct": percentile_from_universe(e.mktcap, mktcap),
        "n_universe": len(e),
        "n_excluded": int((~u.eligible).sum()),
    }


@lru_cache(maxsize=1)
def _db_frame() -> pd.DataFrame:
    import duckdb

    from src.db.build import DB_PATH
    from src.premium.p2c3 import load_frame

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return load_frame(con)
    finally:
        con.close()


def fit_all(df: pd.DataFrame) -> dict[float, pd.Series]:
    """Quantile regressions for every quantile of QS."""
    return {q: fit_qr(df, q) for q in QS}


@lru_cache(maxsize=1)
def _db_params() -> dict[float, pd.Series]:
    """fit_all on the DB sample, once per process (P7-C2 speed: about 1.3 s per premium_range call before; same values)."""
    return fit_all(_db_frame())


ADOPT_THRESHOLD = 0.05
GAP_WARNING = "differ by more than 10%p"


@lru_cache(maxsize=1)
def application_rule() -> dict:
    """The registered rule that picks regression / neighbours / band table (decision D6)."""
    from src.premium.p2c3 import load_cfg

    return load_cfg()["application_rule"]


def choose_method(
    market: str, mktcap_pct: float, adopted: bool, warnings: list[str], rule: dict | None = None
) -> tuple[str, str]:
    """D6: which output is the primary range -> (method, reason). Pure function (unit-tested)."""
    r = rule or application_rule()
    if market == "KOSPI":
        return "neighbours", "rule_market"
    if mktcap_pct >= r["top_band_pct"]:
        return "neighbours", "rule_top_band"
    if adopted:
        if any(GAP_WARNING in w for w in warnings):
            return "neighbours", "warning"
        return "regression", "cv_adopted"
    return "band_table", "cv_not_adopted"


def adoption(df: pd.DataFrame) -> float:
    """Pre-registered decision input: 5-fold CV improvement of the q50 pinball loss over the unconditional median."""
    from src.premium.p2c3 import cross_validate

    return float(cross_validate(df)["q50"]["improvement"])


@lru_cache(maxsize=1)
def _db_adoption() -> float:
    return adoption(_db_frame())


def premium_range(
    mktcap_pct: float,
    stake_band: str = "lt25",
    buyer_group: str = "strategic",
    market: str = "KOSDAQ",
    period: str = "2015-2026",
    data: pd.DataFrame | None = None,
    params: dict | None = None,
) -> PremiumRange:
    """Conditional premium range. `data` / `params` let tests pass a synthetic sample (default: the DB sample)."""
    if (
        stake_band not in STAKE_BANDS
        or buyer_group not in BUYER_GROUPS
        or market not in ("KOSDAQ", "KOSPI")
        or period not in PERIODS
        or not (0 <= mktcap_pct <= 100)
    ):
        raise ValueError("invalid input")
    df = _db_frame() if data is None else data
    params = params or (_db_params() if data is None else fit_all(df))
    imp = _db_adoption() if data is None else adoption(df)
    adopted = imp >= ADOPT_THRESHOLD
    pt = pd.DataFrame(
        [
            {
                "mktcap_pct": float(mktcap_pct),
                "stake_band": stake_band,
                "buyer_group": buyer_group,
                "kospi": int(market == "KOSPI"),
                "period_early": PERIODS[period],
            }
        ]
    )
    reg = {q: float(predict_qr(params[q], pt)[0]) for q in QS}
    nb = neighbours(df, mktcap_pct, market, K)
    nq = nb.prem_bu20_doc.quantile(list(QS)).to_list()
    band = quintile_band(mktcap_pct)
    bt = df[(df.market == market) & (df.mktcap_pct.map(quintile_band) == band)].prem_bu20_doc
    warn = []
    rng = df[df.market == market].mktcap_pct
    if len(rng) == 0 or mktcap_pct < rng.min() or mktcap_pct > rng.max():
        warn.append(f"extrapolation: {market} sample percentile range {rng.min():.1f}~{rng.max():.1f}")
    cell = df[
        (df.market == market)
        & (df.stake_band == stake_band)
        & (df.buyer_group == buyer_group)
        & (df.period_early == PERIODS[period])
    ]
    if len(cell) < 10:
        warn.append(f"cell n<10: {len(cell)} deals with the same market/stake band/buyer group/period")
    if abs(reg[0.5] - nq[1]) > GAP_WARN:
        warn.append(f"regression q50 {reg[0.5]:.1%} vs neighbour median {nq[1]:.1%} {GAP_WARNING}")
    if (nb.market != market).any():
        warn.append(f"neighbours filled from the other market: {int((nb.market != market).sum())} of {K}")
    srt = sorted(reg.values())
    if srt != [reg[q] for q in QS]:
        warn.append("quantile crossing at this point (q25/q50/q75 not ordered)")
    if not adopted and bt.size < 10:
        warn.append(f"band table cell n<10: {bt.size} deals in {market} {band}")
    method, reason = choose_method(market, float(mktcap_pct), adopted, warn)
    if method == "regression":
        prim = (reg[0.25], reg[0.5], reg[0.75])
    elif method == "neighbours":
        prim = tuple(float(x) for x in nq)
    else:
        prim = (float(bt.quantile(0.25)), float(bt.median()), float(bt.quantile(0.75))) if bt.size else (np.nan,) * 3
    return PremiumRange(
        q25=prim[0],
        q50=prim[1],
        q75=prim[2],
        method=method,
        reason=reason,
        regression={"q25": reg[0.25], "q50": reg[0.5], "q75": reg[0.75]},
        cv_improvement_q50=imp,
        neighbour={
            "q25": nq[0],
            "q50": nq[1],
            "q75": nq[2],
            "n": len(nb),
            "n_same_market": int((nb.market == market).sum()),
            "pct_range": (float(nb.mktcap_pct.min()), float(nb.mktcap_pct.max())),
        },
        band={
            "band": band,
            "n": int(bt.size),
            "q25": float(bt.quantile(0.25)) if bt.size else np.nan,
            "q50": float(bt.median()) if bt.size else np.nan,
            "q75": float(bt.quantile(0.75)) if bt.size else np.nan,
        },
        warnings=warn,
        inputs={
            "mktcap_pct": mktcap_pct,
            "stake_band": stake_band,
            "buyer_group": buyer_group,
            "market": market,
            "period": period,
        },
    )
