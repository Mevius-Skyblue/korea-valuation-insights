"""P3-A beta table: target + peers, 2 frequencies x 2 indices, unlevered with each company's period-average D/E.

Run: python -m src.valuation.beta_p3            -> DB table beta_p3 (한국거래소 통계정보 기반 계산값)

For each company (config/peers.yaml) and spec in {weekly_2y, monthly_5y} x index in {KOSDAQ, KOSPI}:
    raw beta, SE, R², n          OLS of adjusted stock returns on index returns (src/market/beta.py)
    Blume                        weight_raw x raw + constant (ledger beta.blume)
    D/E points                   every FY / H1 balance-sheet date inside the regression window
                                 D = total debt + lease liabilities (CFS, else OFS), E = KRX market cap on the last
                                 trading day on or before that date (shares actually listed that day)
    de_avg                       mean of the points  -> unlever (Hamada, t = ledger beta.tax_for_hamada)
    de_asof                      2026-06-30 debt / as-of market cap (sensitivity)
The same D/E rule is used to relever (src/valuation/wacc.py): target D/E = peer median of de_avg (ledger).
Short histories (listed after the window start, e.g. SPAC mergers) are flagged, not dropped.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from src.db.build import DB_PATH
from src.market.beta import SPECS, ols_beta, period_returns, stock_and_market, unlever, window_start
from src.market.beta_table import companies, debt_at, mktcap_at
from src.valuation.assumptions import load_ledger

P3_SPECS = ("weekly_2y", "monthly_5y")
INDICES = ("KOSDAQ", "KOSPI")


def bs_points(as_of: str, years: int) -> list[tuple[int, str, str]]:
    """(fiscal_year, period, date) of FY / H1 balance-sheet dates in (as_of - years, as_of]."""
    start, end = window_start(as_of, years), pd.Timestamp(as_of)
    out = []
    for y in range(start.year, end.year + 1):
        for p, md in (("H1", "06-30"), ("FY", "12-31")):
            d = pd.Timestamp(f"{y}-{md}")
            if start < d <= end:
                out.append((y, p, d.strftime("%Y-%m-%d")))
    return out


def de_points(con, c: dict, points: list[tuple[int, str, str]]) -> pd.DataFrame:
    rows = []
    for y, p, d in points:
        b, m = debt_at(con, c["corp_code"], y, p), mktcap_at(con, c["stock_code"], d)
        if b and m:
            rows.append(
                {
                    "date": d,
                    "fs_div": b["fs_div"],
                    "debt": b["debt"],
                    "lease": b["lease"],
                    "mktcap": m,
                    "de": (b["debt"] + b["lease"]) / m,
                }
            )
    return pd.DataFrame(rows)


def first_trade(con, stock_code: str):
    r = con.execute("SELECT min(bas_dd) FROM price_daily WHERE stock_code=?", [stock_code]).fetchone()
    return pd.Timestamp(r[0]) if r and r[0] else None


def build(as_of: str | None = None, cfg_path: str | None = None, table: str = "beta_p3") -> pd.DataFrame:
    """cfg_path: company config (default RF); table: output DB table (P3-C2: beta_jw)."""
    led = load_ledger()
    as_of = as_of or led["meta"]["as_of"]
    w, k = led["beta"]["blume"]["weight_raw"], led["beta"]["blume"]["constant"]
    t = led["beta"]["tax_for_hamada"]
    con = duckdb.connect(str(DB_PATH))
    rows = []
    for c in companies(cfg_path):
        spot = debt_at(con, c["corp_code"], 2026, "H1")
        e_asof = mktcap_at(con, c["stock_code"], as_of)
        de_asof = (spot["debt"] + spot["lease"]) / e_asof if spot and e_asof else None
        listed = first_trade(con, c["stock_code"])
        for spec in P3_SPECS:
            freq, years = SPECS[spec]
            start = window_start(as_of, years)
            pts = de_points(con, c, bs_points(as_of, years))
            de_avg = float(pts.de.mean()) if len(pts) else None
            for idx in INDICES:
                df = stock_and_market(con, c["stock_code"], idx, start.date(), pd.Timestamp(as_of).date())
                rets = period_returns(df[["ret_adj", "mret"]].astype(float), freq)
                res = ols_beta(rets["mret"].to_numpy(), rets["ret_adj"].to_numpy())
                blume = None if res.beta is None else w * res.beta + k
                warn = []
                if res.r2 is not None and res.r2 < 0.1:
                    warn.append("R2<0.1")
                if len(df) and float((df["volume"] == 0).mean()) > 0.05:
                    warn.append("zero-volume>5%")
                if listed is not None and listed > start:
                    warn.append(f"short-history(listed {listed:%Y-%m})")
                rows.append(
                    {
                        "name": c["name"],
                        "tier": c["tier"],
                        "stock_code": c["stock_code"],
                        "spec": spec,
                        "index": idx,
                        "raw": res.beta,
                        "se": res.se,
                        "r2": res.r2,
                        "n": res.n,
                        "blume": blume,
                        "de_avg": de_avg,
                        "de_points": len(pts),
                        "de_asof": de_asof,
                        "bu_avg": unlever(blume, t, de_avg),
                        "bu_asof": unlever(blume, t, de_asof),
                        "bu_raw_avg": unlever(res.beta, t, de_avg),
                        "tax": t,
                        "as_of": as_of,
                        "warn": ",".join(warn),
                    }
                )
    out = pd.DataFrame(rows)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM out")
    con.close()
    return out


def peer_stats(df: pd.DataFrame, tiers=("core", "extended"), col: str = "bu_avg") -> pd.DataFrame:
    """Median and quartiles of the unlevered beta (and of de_avg) across peers, per spec x index."""
    p = df[df.tier.isin(tiers)]
    g = p.groupby(["spec", "index"])
    return pd.DataFrame(
        {
            "n": g[col].count(),
            "q25": g[col].quantile(0.25),
            "median": g[col].median(),
            "q75": g[col].quantile(0.75),
            "de_avg_median": g["de_avg"].median(),
        }
    ).reset_index()


if __name__ == "__main__":
    d = build()
    print(len(d), "rows written to beta_p3")
    print(peer_stats(d).to_string())
