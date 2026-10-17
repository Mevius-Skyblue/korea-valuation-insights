"""P5-B reference values for the Excel model and the report (P6-A, display only - no path or verdict changes).

    achievement(con)   SPAC forecast achievement (actual / forecast) by account x year-after-merger h: n, median, Q1, Q3
                       (same rows and definitions as reports/p5b_final.md section 4: h = 1~3, partial years out)
    cagr_bands(con)    forecast revenue CAGR quartile bands -> revenue achievement median per band and h
                       (same CAGR as the Spearman analysis, section 5)
    srp_cites(con)     한공회 size-premium values quoted in the opinions (2nd-hand 🔸), grouped by cited year x band x value
    srp_cite_pick(con) the value for one band from the latest filing that quotes it (the 'SRP 인용 참고값')
Rules: config/valuation_rules.yaml p5b_reference. Only aggregates leave this module (no deal list).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.collect.core import ROOT


def rules() -> dict:
    return yaml.safe_load((ROOT / "config" / "valuation_rules.yaml").read_text(encoding="utf-8"))["p5b_reference"]


def forecast_cagr(f: pd.DataFrame) -> dict[str, float]:
    """Forecast revenue CAGR per deal: first full forecast year -> last forecast year (partial years out)."""
    fr = f[(f.account == "revenue") & ~f.partial].sort_values(["deal_id", "fiscal_year"])
    out = {}
    for did, g in fr.groupby("deal_id"):
        if len(g) >= 2 and g.forecast.iloc[0] > 0 and g.forecast.iloc[-1] > 0:
            n = int(g.fiscal_year.iloc[-1] - g.fiscal_year.iloc[0])
            out[did] = (g.forecast.iloc[-1] / g.forecast.iloc[0]) ** (1 / n) - 1 if n > 0 else None
    return out


def _errors(con) -> pd.DataFrame:
    e = con.execute("SELECT * FROM p5b_error").df()
    e = e[(e.h >= 1) & (e.h <= 3) & ~e.partial & e.spac].copy()
    e["h"] = e.h.astype(int)
    return e


def achievement(con) -> list[dict]:
    """Rows {account, h, n, median, q1, q3}. n = all rows (as in the report); quantiles over forecast > 0."""
    r = rules()
    e = _errors(con)
    out = []
    for acc in r["accounts"]:
        for h in r["horizons"]:
            g = e[(e.account == acc) & (e.h == h)]
            pos = g[g.forecast > 0].achievement
            out.append({"account": acc, "h": h, "n": len(g), "median": float(pos.median()),
                        "q1": float(pos.quantile(0.25)), "q3": float(pos.quantile(0.75))})
    return out


def cagr_bands(con) -> dict:
    """Quartile edges of the forecast revenue CAGR (deals with an h = 1 revenue achievement) and, per band, the revenue
    achievement median and n for each h. Bands: [min, q1), [q1, q2), [q2, q3), [q3, max]."""
    r = rules()
    e = _errors(con)
    cg = forecast_cagr(con.execute("SELECT * FROM p5b_forecast").df())
    rev = e[(e.account == "revenue") & (e.forecast > 0)].assign(cagr=lambda x: x.deal_id.map(cg)).dropna(subset=["cagr"])
    base = rev[rev.h == 1].drop_duplicates("deal_id")
    q = [float(v) for v in np.quantile(base.cagr, [0.25, 0.5, 0.75])]
    edges = [float(base.cagr.min())] + q + [float(base.cagr.max())]
    idx = lambda v: int(np.searchsorted(q, v, side="right"))  # noqa: E731     0..3
    rev = rev.assign(band=rev.cagr.map(idx))
    bands = []
    for b in range(4):
        row = {"band": b, "lo": edges[b], "hi": edges[b + 1], "n_deals": int((base.cagr.map(idx) == b).sum())}
        for h in r["horizons"]:
            g = rev[(rev.band == b) & (rev.h == h)].achievement
            row[f"h{h}_median"], row[f"h{h}_n"] = (float(g.median()) if len(g) else None), len(g)
        bands.append(row)
    return {"edges": edges, "bands": bands, "n_base": len(base)}


def srp_cites(con) -> list[dict]:
    c = con.execute("SELECT * FROM p5b_srp_cites").df()
    c["cited"] = c.cited_year.map(lambda v: str(int(v)) if v == v and v is not None else "미추출")
    c["band"] = c.band.fillna("(미추출)")
    c["filed"] = c.rcept_no.str[:4]
    g = c.groupby(["cited", "band", "srp"]).agg(n=("rcept_no", "count"), filed=("filed", lambda s: "~".join(sorted({min(s), max(s)}))))
    return [{"cited": k[0], "band": k[1], "srp": round(float(k[2]), 6), "n": int(v.n), "filed": v.filed} for k, v in g.iterrows()]


def srp_cite_pick(con, band: str | None = None) -> dict:
    band = band or rules()["srp_cite_band"]
    c = con.execute("SELECT * FROM p5b_srp_cites WHERE band=? ORDER BY rcept_no DESC", [band]).df()
    v = round(float(c.srp.iloc[0]), 6)            # DB DOUBLE 0.0401999.. -> 0.0402
    same = c[(c.srp - v).abs() < 1e-9]
    return {"band": band, "value": v, "n": len(same), "filed": f"{same.rcept_no.min()[:4]}~{same.rcept_no.max()[:4]}",
            "latest_filed": c.rcept_no.iloc[0][:8]}


def excel_data(con) -> dict:
    r = rules()
    return {"achievement": achievement(con), "cagr": cagr_bands(con), "srp_cites": srp_cites(con), "srp_pick": srp_cite_pick(con),
            "target_cagr_years": r["target_cagr_years"], "note": r["note"], "source": f"{r['source_report']} (커밋 {r['source_commit']}), DB p5b_error·p5b_forecast·p5b_srp_cites",
            "status": r["status"]}
