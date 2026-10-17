"""P3-C3 common rules for every company (config/valuation_rules.yaml `common_rules`, pre-registered in bf5211c).

    beta_reliability(r2s)          peer R² median < warn threshold -> warning text (display only, path unchanged)
    kd_choice(rating, actual, rates, rf)
                                   pre-tax Kd by rating band, floored at Rf:
                                   unrated -> BBB- 3y; AA- or better -> AA- 3y; A+ ~ BBB+ -> max(actual, AA- 3y)
                                   (sensitivities: notch-linear AA- -> BBB-, BBB- 3y); BBB or below -> BBB- 3y
    start_nopat(fy_revenue, margin, tax_rate)
                                   NOPAT of the start year for incremental ROIC = revenue x normal margin x (1 − t)
    ltm_periods(meta)              (FY year, LTM year, LTM period) from a company config meta
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

from src.collect.core import ROOT

RULES = ROOT / "config" / "valuation_rules.yaml"


def load_common(path: Path = RULES) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["common_rules"]


def beta_reliability(r2s, rules: dict | None = None) -> dict:
    r = (rules or load_common())["beta"]
    med = float(np.nanmedian(list(r2s))) if len(list(r2s)) else float("nan")
    warn = med < r["warn_r2_median_below"]
    return {"r2_median": med, "warn": bool(warn),
            "text": f"회귀 베타 신뢰 낮음(피어 R² 중앙값 {med:.2f} < {r['warn_r2_median_below']:.2f})" if warn else ""}


def kd_choice(rating: str | None, actual: float | None, rates: dict, rf: float, rules: dict | None = None) -> dict:
    """rates: {'CB3Y_AAm': .., 'CB3Y_BBBm': ..} (decimals). Returns base Kd, label and sensitivities."""
    r = (rules or load_common())["kd"]
    scale = r["rating_scale"]
    aa, bbb = rates[r["aa_minus_or_better"]], rates[r["unrated"]]
    sens = {}
    if not rating:
        kd, lab = bbb, "무등급 → BBB- 3년"
    else:
        i, i_aa, i_bbbp = scale.index(rating), scale.index("AA-"), scale.index("BBB+")
        if i <= i_aa:
            kd, lab = aa, f"{rating} (AA- 이상) → AA- 3년"
        elif i <= i_bbbp:
            base = max(actual if actual is not None else -np.inf, aa)
            kd, lab = base, f"{rating} (A+~BBB+) → max(실제 {actual:.3%}, AA- {aa:.3%})" if actual is not None else f"{rating} → AA- 3년"
            steps = scale.index("BBB-") - i_aa
            sens = {"등급 선형 보간": aa + (bbb - aa) * (i - i_aa) / steps, "BBB- 3년": bbb}
        else:
            kd, lab = bbb, f"{rating} (BBB 이하) → BBB- 3년"
    floored = max(kd, rf) if r["floor"] == "rf" else kd
    if floored > kd:
        lab += f" → Rf 하한 {rf:.3%}"
    return {"kd": floored, "label": lab, "sensitivity": sens}


def start_nopat(fy_revenue: float, margin: float, tax_fn) -> float:
    ebit = fy_revenue * margin
    return ebit - tax_fn(ebit)


def ltm_periods(meta: dict) -> tuple[int, int, str]:
    y, p = int(meta["ltm"]["year"]), meta["ltm"]["period"]
    return y - 1, y, p
