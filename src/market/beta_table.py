"""Beta table for the target and peers (config/peers.yaml) -> DB table beta_estimates.

Run: python -m src.market.beta_table [as_of=2026-09-30]

D/E inputs
    D  = total_debt (borrowings + bonds incl. CB/EB/BW) [+ lease liabilities in the "incl. lease" version]
         from the latest balance sheet on or before as_of (default values, CFS else OFS)
    E  = market capitalisation at as_of (price_daily.mktcap, 한국거래소 통계정보)
    avg = mean of D/E at the balance-sheet dates inside the 2-year window (FY2024, H1 2025, FY2025, H1 2026),
          E taken on the last trading day on or before each date
t: config/discount_inputs.yaml corporate_tax.beta_default (sensitivity: beta_sensitivity)
"""
from __future__ import annotations

import sys

import duckdb
import pandas as pd
import yaml

from src.collect.core import ROOT
from src.db.build import DB_PATH

from .beta import SPECS, estimate, unlever

BS_POINTS = [(2024, "FY", "2024-12-31"), (2025, "H1", "2025-06-30"), (2025, "FY", "2025-12-31"), (2026, "H1", "2026-06-30")]


def companies(cfg_path: str | None = None) -> list[dict]:
    """Target + peers of a company config (default: RF config/peers.yaml; P3-C2: any config/valuation_*.yaml with
    the same target / peers keys)."""
    cfg = yaml.safe_load((ROOT / (cfg_path or "config/peers.yaml")).read_text(encoding="utf-8"))
    t = cfg["target"]
    return [{"name": t["name"], "stock_code": t["stock_code"], "corp_code": t["corp_code"], "tier": "target"}] + \
        [{k: p[k] for k in ("name", "stock_code", "corp_code", "tier")} for p in cfg["peers"]]


def tax_rates() -> tuple[float, float]:
    cfg = yaml.safe_load((ROOT / "config" / "discount_inputs.yaml").read_text(encoding="utf-8"))
    return cfg["corporate_tax"]["beta_default"], cfg["corporate_tax"]["beta_sensitivity"]


def debt_at(con, corp: str, year: int, period: str, fs_div: str | None = None) -> dict | None:
    """fs_div None: CFS when present, else OFS (P1 rule). P7-B3 SOTP parents pass 'OFS'."""
    rows = con.execute("""SELECT fs_div, std_account, amount FROM fs_std
                          WHERE corp_code=? AND fiscal_year=? AND period=? AND is_default
                            AND std_account IN ('total_debt','lease_liabilities','total_assets')""",
                       [corp, year, period]).fetchall()
    if not rows:
        return None
    fs = fs_div if fs_div and any(r[0] == fs_div for r in rows) else ("CFS" if any(r[0] == "CFS" for r in rows) else "OFS")
    v = {a: int(x) for f, a, x in rows if f == fs}
    if "total_assets" not in v:
        return None
    return {"fs_div": fs, "debt": v.get("total_debt", 0), "lease": v.get("lease_liabilities", 0)}


def mktcap_at(con, stock_code: str, date: str) -> int | None:
    # bonus-issue windows use the corrected market cap (P3-B); mktcap_fix may not exist in an old DB
    has_fix = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'mktcap_fix'").fetchone()[0]
    if has_fix:
        r = con.execute("""SELECT coalesce(f.mktcap_fix, d.mktcap) FROM price_daily d LEFT JOIN mktcap_fix f
                           ON f.stock_code = d.stock_code AND f.bas_dd = d.bas_dd
                           WHERE d.stock_code=? AND d.bas_dd<=? ORDER BY d.bas_dd DESC LIMIT 1""", [stock_code, date]).fetchone()
        return int(r[0]) if r else None
    r = con.execute("""SELECT mktcap FROM price_daily WHERE stock_code=? AND bas_dd<=? ORDER BY bas_dd DESC LIMIT 1""",
                    [stock_code, date]).fetchone()
    return int(r[0]) if r else None


def leverage(con, c: dict, as_of: str) -> dict:
    spot = debt_at(con, c["corp_code"], 2026, "H1")
    e = mktcap_at(con, c["stock_code"], as_of)
    out = {"bs_basis": f"2026H1 {spot['fs_div']}" if spot else None, "mktcap": e,
           "debt": spot["debt"] if spot else None, "lease": spot["lease"] if spot else None}
    out["de_ex"] = spot["debt"] / e if spot and e else None
    out["de_inc"] = (spot["debt"] + spot["lease"]) / e if spot and e else None
    pts = []
    for y, p, d in BS_POINTS:
        b, m = debt_at(con, c["corp_code"], y, p), mktcap_at(con, c["stock_code"], d)
        if b and m:
            pts.append(((b["debt"]) / m, (b["debt"] + b["lease"]) / m))
    out["de_ex_avg"] = sum(x for x, _ in pts) / len(pts) if pts else None
    out["de_inc_avg"] = sum(y for _, y in pts) / len(pts) if pts else None
    out["de_points"] = len(pts)
    return out


def build(as_of: str = "2026-09-30") -> pd.DataFrame:
    t, t_sens = tax_rates()
    con = duckdb.connect(str(DB_PATH))
    rows = []
    for c in companies():
        lev = leverage(con, c, as_of)
        for idx in ("KOSPI", "KOSDAQ"):
            for spec in SPECS:
                e = estimate(con, c["stock_code"], idx, as_of, spec)
                rec = {"name": c["name"], "tier": c["tier"], **e, **lev, "as_of": as_of, "tax": t}
                for lab, de in (("ex", lev["de_ex"]), ("inc", lev["de_inc"]),
                                ("ex_avg", lev["de_ex_avg"]), ("inc_avg", lev["de_inc_avg"])):
                    rec[f"bu_raw_{lab}"] = unlever(e["raw"], t, de)
                    rec[f"bu_blume_{lab}"] = unlever(e["blume"], t, de)
                rec["bu_blume_inc_tsens"] = unlever(e["blume"], t_sens, lev["de_inc"])
                rows.append(rec)
    df = pd.DataFrame(rows)
    con.execute("DROP TABLE IF EXISTS beta_estimates")
    con.execute("CREATE TABLE beta_estimates AS SELECT * FROM df")
    con.close()
    return df


if __name__ == "__main__":
    d = build(*(sys.argv[1:] or []))
    print(len(d), "rows written to beta_estimates")
