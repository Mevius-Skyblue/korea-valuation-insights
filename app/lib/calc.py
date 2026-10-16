"""User-input DCF calculator (page 3). Uses the project engine's pure functions only:
src/valuation/wacc.wacc (CAPM + Hamada relever + after-tax Kd) and src/valuation/dcf.run_dcf (FCFF, mid-year, Gordon
and Exit terminal value, implied multiple / g). No market data: every number is typed by the user.

Forecast per year t = 1..N (calendar years first_year .. first_year + N - 1, discounted to the end of first_year - 1):
    revenue_t = revenue_{t-1} x (1 + growth_t)          revenue_0 = base revenue
    EBIT_t    = revenue_t x margin_t
    D&A_t     = revenue_t x dna%,  CAPEX_t = revenue_t x capex%
    ΔNWC_t    = nwc% x (revenue_t - revenue_{t-1})
    tax       = flat rate on EBIT (losses pay 0)
"""
from __future__ import annotations

from datetime import date

from src.valuation.dcf import Period, flat_tax, run_dcf
from src.valuation.wacc import wacc

DEFAULTS = {
    "revenue0": 1000.0, "first_year": 2027, "growth": [0.15, 0.12, 0.10, 0.08, 0.06], "margin": [0.10, 0.11, 0.12, 0.12, 0.12],
    "dna_pct": 0.04, "capex_pct": 0.05, "nwc_pct": 0.10, "tax": 0.22, "rf": 0.035, "mrp": 0.08, "beta_u": 1.0, "srp": 0.0,
    "de": 0.20, "kd": 0.05, "g": 0.01, "exit_multiple": 0.0, "mid_year": True, "net_debt": 0.0, "shares": 0.0,
    "unit_to_won": 100_000_000.0, "wacc_steps": [-0.02, -0.01, 0.0, 0.01, 0.02], "g_values": [0.0, 0.005, 0.01, 0.015, 0.02],
}


def periods(inp: dict) -> tuple[list[Period], list[float]]:
    """Annual periods and the revenue path (revenue_0 first)."""
    rev = [float(inp["revenue0"])]
    out = []
    for i, (gr, m) in enumerate(zip(inp["growth"], inp["margin"])):
        y = int(inp["first_year"]) + i
        r = rev[-1] * (1 + gr)
        out.append(Period(str(y), date(y, 1, 1), date(y, 12, 31), ebit=r * m, dna=r * inp["dna_pct"], capex=r * inp["capex_pct"],
                          dnwc=inp["nwc_pct"] * (r - rev[-1])))
        rev.append(r)
    return out, rev


def forecast_cagr(rev: list[float], years: int = 5) -> float | None:
    """Forecast revenue CAGR from the first forecast year over `years` forecast years (P6-A rule: FY1 -> FY5)."""
    path = rev[1:]
    k = min(years, len(path))
    if k < 2 or path[0] <= 0 or path[k - 1] <= 0:
        return None
    return (path[k - 1] / path[0]) ** (1 / (k - 1)) - 1


def calculate(inp: dict) -> dict:
    w = wacc(inp["rf"], inp["mrp"], inp["beta_u"], inp["de"], inp["kd"], inp["tax"], inp["tax"], inp["srp"])
    ps, rev = periods(inp)
    disc = date(int(inp["first_year"]) - 1, 12, 31)
    tax = flat_tax(inp["tax"])
    ex = inp["exit_multiple"] or None
    r = run_dcf(ps, tax, w.wacc, disc, g=inp["g"], exit_multiple=ex, mid_year=inp["mid_year"])
    grid = {}
    for dw in inp["wacc_steps"]:
        for gg in inp["g_values"]:
            ww = w.wacc + dw
            grid[(dw, gg)] = run_dcf(ps, tax, ww, disc, g=gg, mid_year=inp["mid_year"]).ev_gordon if ww > gg else None
    equity = r.ev_gordon - inp["net_debt"]
    per_share = equity * inp["unit_to_won"] / inp["shares"] if inp["shares"] > 0 else None
    return {"wacc": w.wacc, "ke": w.ke, "beta_l": w.beta_l, "kd_after_tax": w.kd_after_tax, "wd": w.wd,
            "ev": r.ev_gordon, "pv_explicit": r.pv_explicit, "pv_tv": r.pv_tv_gordon, "tv_share": r.tv_share_gordon,
            "implied_multiple": r.implied_multiple, "ev_exit": r.ev_exit, "implied_g": r.implied_g, "equity": equity,
            "per_share": per_share, "grid": grid, "table": r.table, "revenue": rev, "cagr5": forecast_cagr(rev)}
