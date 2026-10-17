"""Period arithmetic on fs_std default values: quarter stand-alone, Q4, LTM.

Flows (income, cash flow) in fs_std are year-to-date (Q1, H1, Q3) or full-year (FY).
    Q2 = H1 - Q1, Q3 alone = Q3ytd - H1, Q4 = FY - Q3ytd
    LTM at (Y, P) = FY(Y-1) + YTD(Y, P) - YTD(Y-1, P);  LTM at (Y, FY) = FY(Y)
Balance-sheet items are point-in-time: no LTM, use the period-end value.
"""
from __future__ import annotations

import pandas as pd

YTD_ORDER = ["Q1", "H1", "Q3", "FY"]


def _val(wide: pd.DataFrame, year: int, period: str, acct: str):
    try:
        v = wide.loc[(year, period), acct]
    except KeyError:
        return None
    return None if pd.isna(v) else int(v)


def to_wide(std: pd.DataFrame, corp_code: str, fs_div: str) -> pd.DataFrame:
    """Default values for one company/fs_div: index (fiscal_year, period), columns std accounts."""
    d = std[(std["corp_code"] == corp_code) & (std["fs_div"] == fs_div) & std["is_default"]]
    return d.pivot_table(index=["fiscal_year", "period"], columns="std_account", values="amount", aggfunc="first")


def quarter_alone(wide: pd.DataFrame, year: int, q: int, acct: str):
    """Three-month value of quarter q (1..4) from YTD figures; None if a part is missing."""
    cur = {1: "Q1", 2: "H1", 3: "Q3", 4: "FY"}[q]
    a = _val(wide, year, cur, acct)
    if q == 1:
        return a
    b = _val(wide, year, {2: "Q1", 3: "H1", 4: "Q3"}[q], acct)
    return None if a is None or b is None else a - b


def ltm(wide: pd.DataFrame, year: int, period: str, acct: str):
    """Last-twelve-months flow ending at (year, period)."""
    if period == "FY":
        return _val(wide, year, "FY", acct)
    fy_prev = _val(wide, year - 1, "FY", acct)
    ytd = _val(wide, year, period, acct)
    ytd_prev = _val(wide, year - 1, period, acct)
    if None in (fy_prev, ytd, ytd_prev):
        return None
    return fy_prev + ytd - ytd_prev


def latest_period(wide: pd.DataFrame, acct: str = "revenue") -> tuple[int, str] | None:
    """Most recent (year, period) that has `acct`."""
    have = [(y, p) for (y, p) in wide.index if not pd.isna(wide.loc[(y, p)].get(acct))]
    if not have:
        return None
    return max(have, key=lambda t: (t[0], YTD_ORDER.index(t[1])))
